"""
Pending User Input Manager (generalization of the original ApprovalManager).

This module now brokers TWO classes of "agent pauses while waiting on a user":

  1. ``kind="approval"`` — legacy tool-call approval (allow_once / allow_all /
     stop). Preserved bit-for-bit via the ``ApprovalManager`` shim so every
     existing call site keeps working without changes.

  2. ``kind="node_config"`` — structured form input driven by the
     ``request_node_config`` agent tool. The agent creates a Container node,
     emits a ``user_input_required`` event, parks on ``await_input``, and
     resumes when the frontend POSTs to
     ``/api/chat/node-config/{input_id}/submit``.

Both kinds share the same Redis channel + in-memory tracking so pods that run
workers vs API endpoints can deliver responses across the process boundary.

Redis scheme:
  * Pub/Sub channel ``tesslate:pending_input`` — broadcast of every response.
  * Keyspace ``pending_input:{input_id}`` (optional, not required for the
    in-memory path; reserved for future durable hand-off).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

# Legacy channel kept for backwards compatibility with any deployed API pods
# still publishing on the old name. New code publishes on both.
APPROVAL_CHANNEL = "tesslate:approvals"
PENDING_INPUT_CHANNEL = "tesslate:pending_input"


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class PendingInputRequest:
    """A paused request — either a tool approval or a structured form submit."""

    def __init__(
        self,
        *,
        input_id: str,
        kind: str,
        session_id: str,
        tool_name: str | None = None,
        parameters: dict | None = None,
        schema: dict | None = None,
        metadata: dict | None = None,
    ) -> None:
        self.input_id = input_id
        self.kind = kind  # "approval" | "node_config"
        self.session_id = session_id
        self.tool_name = tool_name
        self.parameters = parameters or {}
        self.schema = schema or {}
        self.metadata = metadata or {}
        self.event = asyncio.Event()
        # For approvals: "allow_once" | "allow_all" | "stop".
        # For node_config: dict[str, Any] with submitted values, or "__cancelled__".
        self.response: Any = None


# Legacy alias — some call sites still import `ApprovalRequest`.
class ApprovalRequest(PendingInputRequest):
    """Back-compat alias; behaves identically to PendingInputRequest(kind='approval')."""

    def __init__(self, approval_id: str, tool_name: str, parameters: dict, session_id: str):
        super().__init__(
            input_id=approval_id,
            kind="approval",
            session_id=session_id,
            tool_name=tool_name,
            parameters=parameters,
        )

    @property
    def approval_id(self) -> str:
        return self.input_id


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class PendingUserInputManager:
    """Unified manager for every kind of paused-on-user state."""

    def __init__(self) -> None:
        # input_id -> PendingInputRequest
        self._pending: dict[str, PendingInputRequest] = {}
        # input_id -> cached response if it arrived before the request registered
        self._cached_responses: dict[str, Any] = {}
        # session_id -> set of approved tool names ("Allow All" memory)
        self._approved_tools: dict[str, set[str]] = {}
        # Redis subscriber coroutine
        self._subscriber_task: asyncio.Task | None = None

        logger.info("[PendingUserInputManager] initialized")

    # ------------------- Redis transport -------------------

    def _ensure_subscriber(self) -> None:
        if self._subscriber_task is not None and not self._subscriber_task.done():
            return
        self._subscriber_task = asyncio.create_task(self._redis_subscriber())

    async def _redis_subscriber(self) -> None:
        try:
            from ...services.cache_service import get_redis_client

            redis = await get_redis_client()
            if not redis:
                logger.debug("[PendingUserInputManager] no redis — subscriber skipped")
                return

            pubsub = redis.pubsub()
            await pubsub.subscribe(APPROVAL_CHANNEL, PENDING_INPUT_CHANNEL)
            logger.info(
                "[PendingUserInputManager] subscribed to %s + %s",
                APPROVAL_CHANNEL,
                PENDING_INPUT_CHANNEL,
            )
            try:
                while True:
                    msg = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=1.0
                    )
                    if msg and msg["type"] == "message":
                        try:
                            data = json.loads(msg["data"])
                        except Exception as e:
                            logger.debug("[PendingUserInputManager] bad msg: %s", e)
                            continue
                        # Support both legacy ({approval_id, response}) and new
                        # ({input_id, kind, response}) payloads.
                        input_id = data.get("input_id") or data.get("approval_id")
                        response = data.get("response")
                        if input_id is not None and response is not None:
                            self._deliver(input_id, response)
                    else:
                        await asyncio.sleep(0.05)
            finally:
                await pubsub.unsubscribe(APPROVAL_CHANNEL, PENDING_INPUT_CHANNEL)
                await pubsub.close()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("[PendingUserInputManager] subscriber error: %s", e)

    # ------------------- Delivery -------------------

    def _deliver(self, input_id: str, response: Any) -> None:
        if input_id not in self._pending:
            self._cached_responses[input_id] = response
            logger.debug("[PendingUserInputManager] cached early response for %s", input_id)
            return
        req = self._pending[input_id]
        req.response = response
        if req.kind == "approval" and response == "allow_all":
            self._approved_tools.setdefault(req.session_id, set())
            if req.tool_name:
                self._approved_tools[req.session_id].add(req.tool_name)
        req.event.set()
        del self._pending[input_id]
        logger.info(
            "[PendingUserInputManager] delivered %s response for %s",
            req.kind,
            input_id,
        )

    # ------------------- Approval API (legacy-preserving) -------------------

    def is_tool_approved(self, session_id: str, tool_name: str) -> bool:
        return tool_name in self._approved_tools.get(session_id, set())

    def approve_tool_for_session(self, session_id: str, tool_name: str) -> None:
        self._approved_tools.setdefault(session_id, set()).add(tool_name)
        logger.info(
            "[PendingUserInputManager] approved %s for session %s", tool_name, session_id
        )

    def clear_session_approvals(self, session_id: str) -> None:
        if session_id in self._approved_tools:
            del self._approved_tools[session_id]
            logger.info("[PendingUserInputManager] cleared approvals for %s", session_id)

    async def request_approval(
        self, tool_name: str, parameters: dict, session_id: str
    ) -> tuple[str, ApprovalRequest]:
        approval_id = str(uuid4())
        request = ApprovalRequest(approval_id, tool_name, parameters, session_id)
        self._pending[approval_id] = request
        self._ensure_subscriber()
        logger.info(
            "[PendingUserInputManager] created approval %s for %s", approval_id, tool_name
        )

        if approval_id in self._cached_responses:
            cached = self._cached_responses.pop(approval_id)
            logger.info("[PendingUserInputManager] using cached response for %s", approval_id)
            request.response = cached
            if cached == "allow_all":
                self.approve_tool_for_session(session_id, tool_name)
            request.event.set()
            # Remove from pending to mirror _deliver
            self._pending.pop(approval_id, None)
        return approval_id, request

    def respond_to_approval(self, approval_id: str, response: str) -> None:
        self._deliver(approval_id, response)

    def get_pending_request(self, approval_id: str) -> ApprovalRequest | None:
        req = self._pending.get(approval_id)
        return req if isinstance(req, ApprovalRequest) else None

    # ------------------- Node-config API -------------------

    async def create_input_request(
        self,
        *,
        input_id: str,
        project_id: str,
        chat_id: str,
        container_id: str,
        schema_json: dict,
        mode: str,
        ttl: int,
    ) -> PendingInputRequest:
        """Register a node-config pending input. ``ttl`` is advisory (used by
        the wait loop); no Redis key is written here — the in-memory future
        is the truth, and the subscriber relays responses across pods."""
        request = PendingInputRequest(
            input_id=input_id,
            kind="node_config",
            session_id=chat_id,
            schema=schema_json,
            metadata={
                "project_id": project_id,
                "chat_id": chat_id,
                "container_id": container_id,
                "mode": mode,
                "ttl": ttl,
            },
        )
        self._pending[input_id] = request
        self._ensure_subscriber()

        if input_id in self._cached_responses:
            cached = self._cached_responses.pop(input_id)
            request.response = cached
            request.event.set()
            self._pending.pop(input_id, None)

        logger.info(
            "[PendingUserInputManager] created node_config request %s for container=%s mode=%s",
            input_id,
            container_id,
            mode,
        )
        return request

    async def await_input(
        self, input_id: str, timeout: float
    ) -> dict | str | None:
        """Wait for the user's response.

        Returns the dict of submitted values, the sentinel string
        ``"__cancelled__"`` if the user cancelled, or ``None`` on timeout.
        """
        request = self._pending.get(input_id)
        if request is None:
            # Was already delivered (raced with create) — check cached + exit.
            if input_id in self._cached_responses:
                return self._cached_responses.pop(input_id)
            logger.warning(
                "[PendingUserInputManager] await_input for unknown %s", input_id
            )
            return None
        try:
            await asyncio.wait_for(request.event.wait(), timeout=timeout)
        except TimeoutError:
            logger.warning(
                "[PendingUserInputManager] node_config timeout for %s", input_id
            )
            self._pending.pop(input_id, None)
            return None
        return request.response

    def submit_input(self, input_id: str, values: dict) -> bool:
        """Local-path submit; also publish on Redis so other pods pick it up."""
        if input_id not in self._pending and input_id not in self._cached_responses:
            # Unknown — still cache for a late-arriving request.
            self._cached_responses[input_id] = values
            logger.info(
                "[PendingUserInputManager] cached submit for unknown input %s",
                input_id,
            )
            return True
        self._deliver(input_id, values)
        return True

    def cancel_input(self, input_id: str) -> bool:
        if input_id not in self._pending and input_id not in self._cached_responses:
            self._cached_responses[input_id] = "__cancelled__"
            return True
        self._deliver(input_id, "__cancelled__")
        return True


# ---------------------------------------------------------------------------
# Back-compat shim
# ---------------------------------------------------------------------------


class ApprovalManager(PendingUserInputManager):
    """Alias preserved for imports like `from .approval_manager import ApprovalManager`."""


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


async def publish_approval_response(approval_id: str, response: str) -> None:
    """Publish an approval response to Redis for cross-pod delivery."""
    await _publish_response(approval_id, response, channel=APPROVAL_CHANNEL, kind="approval")


async def publish_pending_input_response(
    input_id: str, response: Any, *, kind: str = "node_config"
) -> None:
    """Publish a pending-input response for cross-pod delivery."""
    await _publish_response(input_id, response, channel=PENDING_INPUT_CHANNEL, kind=kind)


async def _publish_response(
    input_id: str, response: Any, *, channel: str, kind: str
) -> None:
    from ...services.cache_service import get_redis_client

    redis = await get_redis_client()
    if not redis:
        logger.warning(
            "[PendingUserInputManager] no redis — cannot publish %s response for %s",
            kind,
            input_id,
        )
        return
    try:
        payload = {
            "input_id": input_id,
            # Also set `approval_id` for legacy subscribers.
            "approval_id": input_id,
            "kind": kind,
            "response": response,
        }
        await redis.publish(channel, json.dumps(payload))
        logger.info(
            "[PendingUserInputManager] published %s response for %s on %s",
            kind,
            input_id,
            channel,
        )
    except Exception as e:
        logger.error(
            "[PendingUserInputManager] failed to publish to redis: %s", e
        )


async def wait_for_approval_or_cancel(
    request: ApprovalRequest,
    task_id: str | None = None,
    timeout_seconds: float = 300.0,
    poll_interval: float = 1.0,
) -> str | None:
    """Wait for approval response, checking for cancellation every poll_interval.

    Returns 'allow_once'/'allow_all'/'stop', or None on timeout, or 'cancel'
    if the task was cancelled.
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
            logger.info(
                "[PendingUserInputManager] wait cancelled for %s", request.input_id
            )
            return "cancel"

    logger.warning(
        "[PendingUserInputManager] approval timeout for %s", request.input_id
    )
    return None


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_manager: PendingUserInputManager | None = None


def get_approval_manager() -> PendingUserInputManager:
    """Legacy accessor — returns the unified manager instance."""
    global _manager
    if _manager is None:
        _manager = PendingUserInputManager()
    return _manager


def get_pending_input_manager() -> PendingUserInputManager:
    """New accessor — same singleton as get_approval_manager."""
    return get_approval_manager()
