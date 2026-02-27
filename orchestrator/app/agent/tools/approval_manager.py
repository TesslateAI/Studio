"""
Tool Approval Manager

Manages per-session tool approvals for "ask before edit" mode.
Tracks which tool types have been approved with "Allow All" for each chat session.

Supports cross-process approval delivery via Redis Pub/Sub so API pods
can relay user responses to ARQ worker pods.
"""

import asyncio
import json
import logging
from uuid import uuid4

logger = logging.getLogger(__name__)

APPROVAL_CHANNEL = "tesslate:approvals"


class ApprovalRequest:
    """Represents a pending tool approval request."""

    def __init__(self, approval_id: str, tool_name: str, parameters: dict, session_id: str):
        self.approval_id = approval_id
        self.tool_name = tool_name
        self.parameters = parameters
        self.session_id = session_id
        self.event = asyncio.Event()
        self.response: str | None = None  # 'allow_once', 'allow_all', 'stop'


class ApprovalManager:
    """
    Manages tool approvals across chat sessions.

    Features:
    - Per-session tool approval tracking
    - "Allow All" approval for specific tool types per session
    - Async wait for user approval responses
    - Redis Pub/Sub for cross-process approval delivery (API pod → worker pod)
    """

    def __init__(self):
        # session_id -> set of approved tool names
        self._approved_tools: dict[str, set[str]] = {}

        # approval_id -> ApprovalRequest
        self._pending_approvals: dict[str, ApprovalRequest] = {}

        # approval_id -> response (for responses that arrive before request is registered)
        self._cached_responses: dict[str, str] = {}

        # Redis subscriber task (started on first approval request)
        self._subscriber_task: asyncio.Task | None = None

        logger.info("[ApprovalManager] Initialized")

    def _ensure_subscriber(self):
        """Start the Redis subscriber if not already running."""
        if self._subscriber_task is not None and not self._subscriber_task.done():
            return
        self._subscriber_task = asyncio.create_task(self._redis_subscriber())

    async def _redis_subscriber(self):
        """Subscribe to Redis approval channel and relay responses to local events."""
        try:
            from ...services.cache_service import get_redis_client

            redis = await get_redis_client()
            if not redis:
                logger.debug("[ApprovalManager] No Redis — subscriber not started")
                return

            pubsub = redis.pubsub()
            await pubsub.subscribe(APPROVAL_CHANNEL)
            logger.info("[ApprovalManager] Redis subscriber started for approval relay")

            try:
                while True:
                    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if msg and msg["type"] == "message":
                        try:
                            data = json.loads(msg["data"])
                            approval_id = data.get("approval_id")
                            response = data.get("response")
                            if approval_id and response:
                                self._handle_redis_approval(approval_id, response)
                        except Exception as e:
                            logger.debug(f"[ApprovalManager] Bad message: {e}")
                    else:
                        await asyncio.sleep(0.05)
            finally:
                await pubsub.unsubscribe(APPROVAL_CHANNEL)
                await pubsub.close()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"[ApprovalManager] Subscriber error: {e}")

    def _handle_redis_approval(self, approval_id: str, response: str):
        """Handle an approval response received via Redis Pub/Sub."""
        if approval_id not in self._pending_approvals:
            # Not for us yet — cache it so request_approval() can pick it up
            self._cached_responses[approval_id] = response
            logger.debug(f"[ApprovalManager] Cached early response for {approval_id}")
            return

        logger.info(f"[ApprovalManager] Received approval via Redis: {response} for {approval_id}")
        request = self._pending_approvals[approval_id]
        request.response = response

        if response == "allow_all":
            self.approve_tool_for_session(request.session_id, request.tool_name)

        # Signal the waiting coroutine
        request.event.set()

        # Clean up
        del self._pending_approvals[approval_id]

    def is_tool_approved(self, session_id: str, tool_name: str) -> bool:
        """
        Check if a tool type has been approved for the session.

        Args:
            session_id: Chat session identifier
            tool_name: Name of the tool to check

        Returns:
            True if tool was approved with "Allow All" for this session
        """
        if session_id not in self._approved_tools:
            return False
        return tool_name in self._approved_tools[session_id]

    def approve_tool_for_session(self, session_id: str, tool_name: str):
        """
        Mark a tool type as approved for the entire session.

        This is called when user clicks "Allow All" for a specific tool.

        Args:
            session_id: Chat session identifier
            tool_name: Tool type to approve
        """
        if session_id not in self._approved_tools:
            self._approved_tools[session_id] = set()

        self._approved_tools[session_id].add(tool_name)
        logger.info(f"[ApprovalManager] Approved {tool_name} for session {session_id}")

    def clear_session_approvals(self, session_id: str):
        """
        Clear all approvals for a session.

        Called when /clear is used or session ends.

        Args:
            session_id: Chat session identifier
        """
        if session_id in self._approved_tools:
            del self._approved_tools[session_id]
            logger.info(f"[ApprovalManager] Cleared approvals for session {session_id}")

    async def request_approval(
        self, tool_name: str, parameters: dict, session_id: str
    ) -> tuple[str, str]:
        """
        Request user approval for a tool execution.

        This function:
        1. Creates an approval request
        2. Starts Redis subscriber (so responses from API pods arrive)
        3. Returns the approval_id for the frontend to display

        Args:
            tool_name: Name of tool requiring approval
            parameters: Tool parameters
            session_id: Chat session identifier

        Returns:
            Tuple of (approval_id, request)
        """
        approval_id = str(uuid4())
        request = ApprovalRequest(approval_id, tool_name, parameters, session_id)

        self._pending_approvals[approval_id] = request
        logger.info(f"[ApprovalManager] Created approval request {approval_id} for {tool_name}")

        # Start Redis subscriber so we can receive cross-process approvals
        self._ensure_subscriber()

        # Check if response already arrived (race condition: response before request)
        if approval_id in self._cached_responses:
            cached = self._cached_responses.pop(approval_id)
            logger.info(f"[ApprovalManager] Using cached response for {approval_id}: {cached}")
            request.response = cached
            if cached == "allow_all":
                self.approve_tool_for_session(session_id, tool_name)
            request.event.set()

        return approval_id, request

    def respond_to_approval(self, approval_id: str, response: str):
        """
        Process user's approval response (local path).

        If the approval is pending locally (same process), resolves it directly.
        If not found locally, this is a no-op — the Redis publish path handles it.

        Args:
            approval_id: ID of the approval request
            response: User's choice ('allow_once', 'allow_all', 'stop')
        """
        if approval_id not in self._pending_approvals:
            logger.warning(f"[ApprovalManager] Unknown approval_id: {approval_id} (will try Redis)")
            return

        request = self._pending_approvals[approval_id]
        request.response = response

        # If "Allow All", mark this tool as approved for the session
        if response == "allow_all":
            self.approve_tool_for_session(request.session_id, request.tool_name)

        # Signal the waiting coroutine
        request.event.set()

        logger.info(f"[ApprovalManager] Received response '{response}' for {approval_id}")

        # Clean up
        del self._pending_approvals[approval_id]

    def get_pending_request(self, approval_id: str) -> ApprovalRequest | None:
        """Get a pending approval request by ID."""
        return self._pending_approvals.get(approval_id)


async def publish_approval_response(approval_id: str, response: str):
    """
    Publish an approval response to Redis so all workers receive it.

    Called by the API pod's /agent/approval endpoint.
    """
    from ...services.cache_service import get_redis_client

    redis = await get_redis_client()
    if not redis:
        logger.warning("[ApprovalManager] No Redis — cannot relay approval to worker")
        return

    try:
        await redis.publish(
            APPROVAL_CHANNEL,
            json.dumps({"approval_id": approval_id, "response": response}),
        )
        logger.info(f"[ApprovalManager] Published approval {approval_id} to Redis")
    except Exception as e:
        logger.error(f"[ApprovalManager] Failed to publish approval to Redis: {e}")


async def wait_for_approval_or_cancel(
    request: ApprovalRequest,
    task_id: str | None = None,
    timeout_seconds: float = 300.0,
    poll_interval: float = 1.0,
) -> str | None:
    """
    Wait for approval response, checking for cancellation every poll_interval.

    Returns the response string ('allow_once', 'allow_all', 'stop'),
    or None on timeout, or 'cancel' if the task was cancelled.
    """
    pubsub = None
    if task_id:
        from ...services.pubsub import get_pubsub

        pubsub = get_pubsub()

    elapsed = 0.0
    while elapsed < timeout_seconds:
        try:
            await asyncio.wait_for(request.event.wait(), timeout=poll_interval)
            return request.response
        except TimeoutError:
            elapsed += poll_interval

        if pubsub and task_id and await pubsub.is_cancelled(task_id):
            logger.info(f"[ApprovalManager] Wait cancelled for {request.approval_id}")
            return "cancel"

    logger.warning(f"[ApprovalManager] Approval timeout for {request.approval_id}")
    return None


# Global instance
_approval_manager: ApprovalManager | None = None


def get_approval_manager() -> ApprovalManager:
    """Get or create the global approval manager instance."""
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = ApprovalManager()
    return _approval_manager
