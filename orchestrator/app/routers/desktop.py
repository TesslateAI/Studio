"""Desktop tray/shell support endpoints.

Thin, always-responsive endpoints consumed by the desktop client:

- ``GET /api/desktop/runtime-probe`` — which runtimes (local/docker/k8s) the
  orchestrator can currently reach.
- ``GET /api/desktop/tray-state`` — tray summary (runtimes + placeholders for
  running projects/agents).

Non-blocking contract: even if a probe raises unexpectedly, the endpoint
returns a well-formed payload with ``ok=False`` and a reason string. The
desktop shell polls these endpoints and must never see a 5xx from a probe.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import AgentTask, User
from ..services.agent_approval import approve_ticket
from ..services.runtime_probe import ProbeResult, get_runtime_probe
from ..users import current_active_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/desktop", tags=["desktop"])


async def _safe_probe(coro) -> dict[str, Any]:
    """Run a probe coroutine, never raising. Unexpected failures become ok=False."""
    try:
        result: ProbeResult = await coro
        return result.to_dict()
    except Exception as exc:  # pragma: no cover - defense-in-depth
        logger.warning("runtime probe raised unexpectedly: %s", exc)
        return {"ok": False, "reason": "Probe failed"}


async def _collect_runtimes(user: User) -> dict[str, dict[str, Any]]:
    probe = get_runtime_probe()
    return {
        "local": await _safe_probe(probe.local_available()),
        "docker": await _safe_probe(probe.docker_available()),
        "k8s": await _safe_probe(probe.k8s_remote_available(user=user)),
    }


@router.get("/runtime-probe")
async def runtime_probe(user: User = Depends(current_active_user)) -> dict[str, Any]:
    return await _collect_runtimes(user)


@router.get("/tray-state")
async def tray_state(user: User = Depends(current_active_user)) -> dict[str, Any]:
    return {
        "runtimes": await _collect_runtimes(user),
        "running_projects": [],
        "running_agents": [],
    }


def _serialize_ticket(ticket: AgentTask) -> dict[str, Any]:
    return {
        "id": str(ticket.id),
        "ref_id": ticket.ref_id,
        "project_id": str(ticket.project_id),
        "parent_task_id": str(ticket.parent_task_id) if ticket.parent_task_id else None,
        "status": ticket.status,
        "title": ticket.title,
        "assignee_agent_id": (
            str(ticket.assignee_agent_id) if ticket.assignee_agent_id else None
        ),
        "requires_approval_for": ticket.requires_approval_for or [],
        "goal_ancestry": ticket.goal_ancestry or [],
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
        "completed_at": ticket.completed_at.isoformat() if ticket.completed_at else None,
    }


@router.get("/agents/tickets")
async def list_agent_tickets(
    project_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    _user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(AgentTask)
    if project_id is not None:
        stmt = stmt.where(AgentTask.project_id == project_id)
    if status is not None:
        stmt = stmt.where(AgentTask.status == status)
    stmt = stmt.order_by(AgentTask.created_at)
    result = await db.execute(stmt)
    tickets = result.scalars().all()
    return {"tickets": [_serialize_ticket(t) for t in tickets]}


@router.post("/agents/{ticket_id}/approve")
async def approve_agent_ticket(
    ticket_id: uuid.UUID,
    _user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    existing = await db.execute(select(AgentTask).where(AgentTask.id == ticket_id))
    ticket = existing.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    await approve_ticket(db, ticket_id=ticket_id)
    return {"ticket_id": str(ticket_id), "status": "queued"}
