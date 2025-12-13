"""
Tool Approval Manager

Manages per-session tool approvals for "ask before edit" mode.
Tracks which tool types have been approved with "Allow All" for each chat session.
"""

import asyncio
import logging
from typing import Dict, Set, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class ApprovalRequest:
    """Represents a pending tool approval request."""

    def __init__(self, approval_id: str, tool_name: str, parameters: Dict, session_id: str):
        self.approval_id = approval_id
        self.tool_name = tool_name
        self.parameters = parameters
        self.session_id = session_id
        self.event = asyncio.Event()
        self.response: Optional[str] = None  # 'allow_once', 'allow_all', 'stop'


class ApprovalManager:
    """
    Manages tool approvals across chat sessions.

    Features:
    - Per-session tool approval tracking
    - "Allow All" approval for specific tool types per session
    - Async wait for user approval responses
    """

    def __init__(self):
        # session_id -> set of approved tool names
        self._approved_tools: Dict[str, Set[str]] = {}

        # approval_id -> ApprovalRequest
        self._pending_approvals: Dict[str, ApprovalRequest] = {}

        logger.info("[ApprovalManager] Initialized")

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
        self,
        tool_name: str,
        parameters: Dict,
        session_id: str
    ) -> tuple[str, str]:
        """
        Request user approval for a tool execution.

        This function:
        1. Creates an approval request
        2. Returns the approval_id for the frontend to display
        3. Waits for user response
        4. Returns the response

        Args:
            tool_name: Name of tool requiring approval
            parameters: Tool parameters
            session_id: Chat session identifier

        Returns:
            Tuple of (approval_id, response) where response is 'allow_once', 'allow_all', or 'stop'
        """
        approval_id = str(uuid4())
        request = ApprovalRequest(approval_id, tool_name, parameters, session_id)

        self._pending_approvals[approval_id] = request
        logger.info(f"[ApprovalManager] Created approval request {approval_id} for {tool_name}")

        # Return approval_id immediately so caller can emit the event
        # Then wait for response
        return approval_id, request

    def respond_to_approval(self, approval_id: str, response: str):
        """
        Process user's approval response.

        Args:
            approval_id: ID of the approval request
            response: User's choice ('allow_once', 'allow_all', 'stop')
        """
        if approval_id not in self._pending_approvals:
            logger.warning(f"[ApprovalManager] Unknown approval_id: {approval_id}")
            return

        request = self._pending_approvals[approval_id]
        request.response = response

        # If "Allow All", mark this tool as approved for the session
        if response == 'allow_all':
            self.approve_tool_for_session(request.session_id, request.tool_name)

        # Signal the waiting coroutine
        request.event.set()

        logger.info(f"[ApprovalManager] Received response '{response}' for {approval_id}")

        # Clean up
        del self._pending_approvals[approval_id]

    def get_pending_request(self, approval_id: str) -> Optional[ApprovalRequest]:
        """Get a pending approval request by ID."""
        return self._pending_approvals.get(approval_id)


# Global instance
_approval_manager: Optional[ApprovalManager] = None


def get_approval_manager() -> ApprovalManager:
    """Get or create the global approval manager instance."""
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = ApprovalManager()
    return _approval_manager
