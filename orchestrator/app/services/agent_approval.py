"""Approval gate for multi-agent orchestration.

Each ``AgentTask`` may declare a ``requires_approval_for`` list of tool
names. Before the agent invokes one of those tools, it calls
``check_tool_allowed`` — if the tool is gated, the ticket is flipped to
``awaiting_approval`` and :class:`ApprovalRequired` is raised so the
caller can suspend the run cleanly.

An operator then calls ``approve_ticket`` (exposed via the desktop
router) to flip the status back to ``queued`` so the worker can pick it
up again.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AgentTask

logger = logging.getLogger(__name__)


class ApprovalRequired(Exception):
    """Raised when a gated tool is hit on an un-approved ticket."""

    def __init__(self, tool_name: str, ticket_id: uuid.UUID) -> None:
        super().__init__(f"tool {tool_name!r} requires approval for ticket {ticket_id}")
        self.tool_name = tool_name
        self.ticket_id = ticket_id


async def check_tool_allowed(
    session: AsyncSession,
    *,
    ticket_id: uuid.UUID,
    tool_name: str,
) -> None:
    """Verify a tool call is allowed on the given ticket.

    Flips status to ``awaiting_approval`` and raises :class:`ApprovalRequired`
    if the tool is in the ticket's ``requires_approval_for`` list. No-op
    otherwise (including missing ticket — the caller already resolved it).
    """
    result = await session.execute(select(AgentTask).where(AgentTask.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if ticket is None:
        return
    required: list[str] | None = ticket.requires_approval_for
    if not required:
        return
    if tool_name not in required:
        return
    now = datetime.now(UTC)
    await session.execute(
        update(AgentTask)
        .where(AgentTask.id == ticket_id)
        .values(status="awaiting_approval", updated_at=now)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    raise ApprovalRequired(tool_name=tool_name, ticket_id=ticket_id)


async def approve_ticket(session: AsyncSession, *, ticket_id: uuid.UUID) -> None:
    """Flip a gated ticket back to ``queued`` for the worker to re-claim."""
    now = datetime.now(UTC)
    await session.execute(
        update(AgentTask)
        .where(AgentTask.id == ticket_id)
        .values(status="queued", updated_at=now)
        .execution_options(synchronize_session=False)
    )
    await session.commit()


__all__ = ["ApprovalRequired", "check_tool_allowed", "approve_ticket"]
