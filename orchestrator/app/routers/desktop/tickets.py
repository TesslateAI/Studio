"""Agent ticket listing and approval endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import AgentTask, User
from ...services.agent_approval import approve_ticket
from ...users import current_active_user
from ._helpers import _serialize_ticket

router = APIRouter()


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
