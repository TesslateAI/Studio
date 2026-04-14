"""
Agent session handoff endpoints — local ↔ cloud continuity for desktop.

- `POST /api/v1/agents/handoff/upload`                — push serialized state, enqueue new task
- `GET  /api/v1/agents/handoff/download/{task_id}`    — pull serialized state for local resume
- `POST /api/v1/agents/handoff/{task_id}/pause`       — soft-cancel, keep state for reuse
- `POST /api/v1/agents/handoff/{task_id}/resume`      — enqueue a new task from a paused snapshot

State serialization lives in `services.public.handoff_service`. Heavy
rate limit on upload — each call enqueues a worker job.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import User
from ...permissions import Permission, get_project_with_access
from ...services.public.handoff_service import (
    build_enqueue_payload,
    bundle_from_payload,
    serialize_task,
)
from ...services.task_manager import TaskStatus, get_task_manager
from ..external_agent import _get_arq_pool
from ._deps import audit_write, scoped

logger = logging.getLogger(__name__)

REQUIRED_SCOPE = Permission.AGENTS_HANDOFF

router = APIRouter(prefix="/api/v1/agents/handoff", tags=["public-agents-handoff"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class UploadRequest(BaseModel):
    project_id: str
    chat_id: str
    message: str
    task_id: str | None = None
    trajectory: list[dict] = []
    file_diff: str | None = None
    goal_ancestry: list[str] = []
    skill_bindings: list[str] = []
    continuation_token: str | None = None
    agent_id: str | None = None
    container_name: str | None = None


class UploadResponse(BaseModel):
    task_id: str
    status: str


class PauseResponse(BaseModel):
    task_id: str
    status: str
    paused: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_owned_task(user: User, task_id: str):
    tm = get_task_manager()
    task = await tm.get_task_async(task_id)
    if not task or str(task.user_id) != str(user.id):
        raise HTTPException(status_code=404, detail="Task not found")
    return task


async def _enqueue_from_bundle(
    *,
    user: User,
    db: AsyncSession,
    bundle,
) -> str:
    project, _role = await get_project_with_access(
        db, bundle.project_id, user.id, Permission.PROJECT_EDIT
    )

    arq_pool = await _get_arq_pool()
    if not arq_pool:
        raise HTTPException(status_code=503, detail="Task queue unavailable (Redis)")

    api_key_record = getattr(user, "_api_key_record", None)
    api_key_scopes = api_key_record.scopes if api_key_record else None

    task_id, payload = build_enqueue_payload(
        bundle,
        user_id=user.id,
        project_slug=project.slug,
        api_key_scopes=api_key_scopes,
    )
    await arq_pool.enqueue_job("execute_agent_task", payload)

    tm = get_task_manager()
    tm.create_task(
        user_id=user.id,
        task_type="agent_execution",
        metadata={
            "project_id": str(project.id),
            "chat_id": bundle.chat_id,
            "message": (bundle.message or "")[:200],
            "origin": "handoff",
            "origin_task_id": bundle.task_id,
            "continuation_token": bundle.continuation_token,
            "skill_bindings": bundle.skill_bindings,
            "goal_ancestry": bundle.goal_ancestry,
        },
        task_id=task_id,
    )
    await tm.update_task_status(task_id, TaskStatus.QUEUED)
    return task_id


# ---------------------------------------------------------------------------
# POST /upload
# ---------------------------------------------------------------------------


@router.post("/upload", response_model=UploadResponse)
async def upload(
    request: UploadRequest,
    user: User = Depends(scoped(Permission.AGENTS_HANDOFF, rate_cost=10, rate_capacity=30)),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    bundle = bundle_from_payload(request.model_dump())
    task_id = await _enqueue_from_bundle(user=user, db=db, bundle=bundle)

    try:
        project_uuid = UUID(bundle.project_id)
    except ValueError:
        project_uuid = None
    await audit_write(
        db=db,
        user=user,
        action="agent_handoff.upload",
        resource_type="agent_task",
        resource_id=None,
        project_id=project_uuid,
        details={
            "task_id": task_id,
            "origin_task_id": bundle.task_id,
            "trajectory_steps": len(bundle.trajectory),
        },
    )
    return UploadResponse(task_id=task_id, status=TaskStatus.QUEUED.value)


# ---------------------------------------------------------------------------
# GET /download/{task_id}
# ---------------------------------------------------------------------------


@router.get("/download/{task_id}")
async def download(
    task_id: str,
    user: User = Depends(scoped(Permission.AGENTS_HANDOFF)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    task = await _get_owned_task(user, task_id)
    bundle = await serialize_task(db, task)
    return bundle.to_dict()


# ---------------------------------------------------------------------------
# POST /{task_id}/pause
# ---------------------------------------------------------------------------


@router.post("/{task_id}/pause", response_model=PauseResponse)
async def pause(
    task_id: str,
    user: User = Depends(scoped(Permission.AGENTS_HANDOFF, rate_cost=2)),
    db: AsyncSession = Depends(get_db),
) -> PauseResponse:
    task = await _get_owned_task(user, task_id)
    if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
        return PauseResponse(task_id=task_id, status=task.status.value, paused=False)

    from ...services.pubsub import get_pubsub

    pubsub = get_pubsub()
    if pubsub is None:
        raise HTTPException(status_code=503, detail="Pause signal unavailable (Redis)")
    await pubsub.request_cancellation(task_id)

    tm = get_task_manager()
    task.metadata = {**(task.metadata or {}), "paused": True}
    await tm.update_task_status(task_id, TaskStatus.CANCELLED)

    project_id_str = (task.metadata or {}).get("project_id")
    await audit_write(
        db=db,
        user=user,
        action="agent_handoff.pause",
        resource_type="agent_task",
        resource_id=None,
        project_id=UUID(project_id_str) if project_id_str else None,
        details={"task_id": task_id},
    )
    return PauseResponse(task_id=task_id, status=TaskStatus.CANCELLED.value, paused=True)


# ---------------------------------------------------------------------------
# POST /{task_id}/resume
# ---------------------------------------------------------------------------


@router.post("/{task_id}/resume", response_model=UploadResponse)
async def resume(
    task_id: str,
    user: User = Depends(scoped(Permission.AGENTS_HANDOFF, rate_cost=10, rate_capacity=30)),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    task = await _get_owned_task(user, task_id)
    bundle = await serialize_task(db, task)
    if not bundle.project_id or not bundle.chat_id:
        raise HTTPException(status_code=400, detail="Source task missing project/chat context")

    new_task_id = await _enqueue_from_bundle(user=user, db=db, bundle=bundle)

    try:
        project_uuid = UUID(bundle.project_id)
    except ValueError:
        project_uuid = None
    await audit_write(
        db=db,
        user=user,
        action="agent_handoff.resume",
        resource_type="agent_task",
        resource_id=None,
        project_id=project_uuid,
        details={"paused_task_id": task_id, "resumed_task_id": new_task_id},
    )
    return UploadResponse(task_id=new_task_id, status=TaskStatus.QUEUED.value)
