"""Handoff client: serialize an agent ticket into a transport bundle.

The unified agents workspace exposes a local ↔ cloud handoff flow where a
ticket can be pushed from the desktop orchestrator to a cloud peer (or
vice-versa). This module is the pure-Python skeleton of that contract:

- ``push`` loads an ``AgentTask`` row and returns a frozen ``HandoffBundle``
  containing the pieces the remote side needs to reconstitute the ticket.
  Today it emits empty trajectory/diff/skill_bindings placeholders — real
  wiring arrives when the trajectory store + git diff integrations land.
- ``pull`` inverts the operation: given a bundle, it allocates a fresh
  local ticket that preserves ``goal_ancestry`` and ``title``.

No network I/O lives here yet; cloud upload/download is a later slice. By
keeping these functions pure we can unit-test the serialization shape
without spinning up an HTTP client.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AgentTask
from .agent_tickets import create_ticket


@dataclass(frozen=True)
class HandoffBundle:
    """Transport-ready snapshot of an agent ticket."""

    ticket_id: str
    title: str | None
    goal_ancestry: list[str]
    trajectory_events: list[dict[str, Any]] = field(default_factory=list)
    diff: str = ""
    skill_bindings: list[dict[str, Any]] = field(default_factory=list)


async def push(session: AsyncSession, *, ticket_id: uuid.UUID) -> HandoffBundle:
    """Load a ticket and serialize it into a ``HandoffBundle``.

    Populates ``diff`` from ``git diff HEAD`` of the ticket's project tree
    (empty when the project has no git root). ``trajectory_events`` and
    ``skill_bindings`` remain placeholders until the trajectory store
    integration lands. Raises ``LookupError`` if the ticket does not exist.
    """
    from sqlalchemy.orm import selectinload

    from .git_diff import git_diff_for_project

    result = await session.execute(
        select(AgentTask)
        .options(selectinload(AgentTask.project))
        .where(AgentTask.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise LookupError(f"ticket {ticket_id} not found")

    diff = await git_diff_for_project(ticket.project) if ticket.project is not None else ""
    skill_bindings = await _load_skill_bindings(session, ticket)

    return HandoffBundle(
        ticket_id=str(ticket.id),
        title=ticket.title,
        goal_ancestry=list(ticket.goal_ancestry or []),
        trajectory_events=[],
        diff=diff,
        skill_bindings=skill_bindings,
    )


async def _load_skill_bindings(
    session: AsyncSession, ticket: AgentTask
) -> list[dict[str, Any]]:
    """Return active skill-assignment rows for the ticket's assignee agent.

    Empty list when the ticket has no assignee, the agent has no skills
    bound, or the lookup fails — skills are advisory metadata so a failure
    should not block the handoff.
    """
    agent_id = getattr(ticket, "assignee_agent_id", None)
    if agent_id is None:
        return []
    from ..models import AgentSkillAssignment, MarketplaceAgent

    stmt = (
        select(AgentSkillAssignment, MarketplaceAgent.slug, MarketplaceAgent.name)
        .join(MarketplaceAgent, MarketplaceAgent.id == AgentSkillAssignment.skill_id)
        .where(AgentSkillAssignment.agent_id == agent_id)
        .where(AgentSkillAssignment.enabled.is_(True))
    )
    try:
        rows = (await session.execute(stmt)).all()
    except Exception:
        return []
    return [
        {"skill_id": str(row[0].skill_id), "slug": row[1], "name": row[2]}
        for row in rows
    ]


async def pull(
    session: AsyncSession,
    *,
    cloud_task_id: str,
    bundle: HandoffBundle,
    project_id: uuid.UUID,
) -> AgentTask:
    """Rehydrate a bundle into a fresh local ticket.

    ``cloud_task_id`` is recorded in ``goal_ancestry`` so the local ticket
    keeps provenance of the remote origin.
    """
    ancestry = list(bundle.goal_ancestry)
    marker = f"cloud:{cloud_task_id}"
    if marker not in ancestry:
        ancestry.append(marker)

    ticket = await create_ticket(
        session,
        project_id=project_id,
        title=bundle.title or "untitled",
        goal_ancestry=ancestry,
    )
    await session.commit()
    return ticket


async def upload_to_cloud(bundle: HandoffBundle) -> str:
    """Upload a bundle to the paired cloud peer.

    Returns the ``cloud_task_id`` assigned by the cloud. Non-blocking: any
    transport error surfaces as the client's own ``NotPairedError`` /
    ``CircuitOpenError`` / ``httpx.TransportError`` so the router can map
    to a clean 4xx/5xx.
    """
    from .cloud_client import get_cloud_client

    client = get_cloud_client()
    resp = await client.post(
        "/api/v1/agents/handoff/upload",
        json={
            "ticket_id": bundle.ticket_id,
            "title": bundle.title,
            "goal_ancestry": bundle.goal_ancestry,
            "trajectory_events": bundle.trajectory_events,
            "diff": bundle.diff,
            "skill_bindings": bundle.skill_bindings,
        },
    )
    data = resp.json()
    return str(data["cloud_task_id"])


async def download_from_cloud(cloud_task_id: str) -> HandoffBundle:
    """Fetch a previously uploaded bundle from the cloud peer."""
    from .cloud_client import get_cloud_client

    client = get_cloud_client()
    resp = await client.get(f"/api/v1/agents/handoff/download/{cloud_task_id}")
    data = resp.json()
    return HandoffBundle(
        ticket_id=str(data["ticket_id"]),
        title=data.get("title"),
        goal_ancestry=list(data.get("goal_ancestry") or []),
        trajectory_events=list(data.get("trajectory_events") or []),
        diff=data.get("diff") or "",
        skill_bindings=list(data.get("skill_bindings") or []),
    )


__all__ = [
    "HandoffBundle",
    "push",
    "pull",
    "upload_to_cloud",
    "download_from_cloud",
]
