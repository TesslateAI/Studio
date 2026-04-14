"""Agent session listing and per-ticket diff endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...database import get_db
from ...models import AgentTask, Directory, User
from ...services.git_diff import git_diff_for_project as _git_diff_for_project
from ...users import current_active_user
from ._helpers import _serialize_session

router = APIRouter()


@router.get("/agents/sessions")
async def list_agent_sessions(
    project_id: uuid.UUID | None = Query(default=None),
    runtime: str | None = Query(default=None),
    status: str | None = Query(default=None),
    directory_id: uuid.UUID | None = Query(default=None),
    _user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(AgentTask).options(
        selectinload(AgentTask.directories), selectinload(AgentTask.project)
    )
    if project_id is not None:
        stmt = stmt.where(AgentTask.project_id == project_id)
    if status is not None:
        stmt = stmt.where(AgentTask.status == status)
    if directory_id is not None:
        stmt = stmt.where(AgentTask.directories.any(Directory.id == directory_id))
    if runtime is not None:
        stmt = stmt.where(AgentTask.directories.any(Directory.runtime == runtime))
    stmt = stmt.order_by(AgentTask.created_at)
    result = await db.execute(stmt)
    tickets = result.scalars().unique().all()
    return {"sessions": [_serialize_session(t) for t in tickets]}


@router.get("/agents/{ticket_id}/diff")
async def agent_ticket_diff(
    ticket_id: uuid.UUID,
    _user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    existing = await db.execute(
        select(AgentTask).options(selectinload(AgentTask.project)).where(AgentTask.id == ticket_id)
    )
    ticket = existing.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    diff = await _git_diff_for_project(ticket.project) if ticket.project is not None else ""
    return {"ticket_id": str(ticket_id), "trajectory": [], "diff": diff}
