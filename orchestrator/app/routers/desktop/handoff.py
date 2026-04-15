"""Agent handoff push/pull endpoints (cloud round-trip)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import User
from ...services.cloud_client import CircuitOpenError, NotPairedError
from ...users import current_active_user

router = APIRouter()


class HandoffPullBody(BaseModel):
    cloud_task_id: str = Field(..., min_length=1, max_length=128)
    project_id: uuid.UUID


@router.post("/agents/{ticket_id}/handoff/push")
async def agents_handoff_push(
    ticket_id: uuid.UUID,
    _user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from ...services import handoff_client

    try:
        bundle = await handoff_client.push(db, ticket_id=ticket_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="ticket not found") from exc
    try:
        cloud_task_id = await handoff_client.upload_to_cloud(bundle)
    except NotPairedError as exc:
        raise HTTPException(status_code=401, detail="sidecar not paired") from exc
    except CircuitOpenError as exc:
        raise HTTPException(status_code=502, detail="cloud unreachable") from exc
    return {"ticket_id": str(ticket_id), "cloud_task_id": cloud_task_id}


@router.post("/agents/handoff/pull")
async def agents_handoff_pull(
    body: HandoffPullBody,
    _user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from ...services import handoff_client

    try:
        bundle = await handoff_client.download_from_cloud(body.cloud_task_id)
    except NotPairedError as exc:
        raise HTTPException(status_code=401, detail="sidecar not paired") from exc
    except CircuitOpenError as exc:
        raise HTTPException(status_code=502, detail="cloud unreachable") from exc
    ticket = await handoff_client.pull(
        db,
        cloud_task_id=body.cloud_task_id,
        bundle=bundle,
        project_id=body.project_id,
    )
    return {
        "ticket_id": str(ticket.id),
        "ref_id": ticket.ref_id,
        "title": ticket.title,
        "cloud_task_id": body.cloud_task_id,
    }
