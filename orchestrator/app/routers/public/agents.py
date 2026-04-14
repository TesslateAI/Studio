"""
Public agent task enumeration, cancellation, and step replay.

Tray-style UX surface — complements the existing per-task invoke/events/status
endpoints in `routers/external_agent.py` by adding:

- `GET  /api/v1/agents/tasks`            — paginated list for the caller
- `POST /api/v1/agents/tasks/{id}/cancel` — graceful cancel via Redis signal
- `GET  /api/v1/agents/tasks/{id}/steps` — paginated AgentStep history

All endpoints are `tsk_`-authenticated and require the `agents.read` scope
(cancel additionally requires `chat.send` because it mutates state).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import AgentStep, User
from ...permissions import Permission
from ...services.task_manager import TaskStatus, get_task_manager
from ._deps import audit_write, scoped
from ._shared import add_cache_headers, paginated_response

logger = logging.getLogger(__name__)

REQUIRED_SCOPE = Permission.AGENTS_READ

router = APIRouter(prefix="/api/v1/agents", tags=["public-agents"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _task_to_dict(task: Any) -> dict:
    return {
        "task_id": task.id,
        "status": task.status.value,
        "type": task.type,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "project_id": (task.metadata or {}).get("project_id"),
        "chat_id": (task.metadata or {}).get("chat_id"),
        "origin": (task.metadata or {}).get("origin"),
        "message_preview": (task.metadata or {}).get("message"),
        "error": task.error,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/agents/tasks — list
# ---------------------------------------------------------------------------


@router.get("/tasks")
async def list_tasks(
    response: Response,
    status: str | None = Query(default=None, description="Filter by status (queued/running/completed/failed/cancelled)"),
    project_id: UUID | None = Query(default=None),
    since: datetime | None = Query(default=None, description="ISO timestamp — only tasks created at/after this"),
    active_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(scoped(Permission.AGENTS_READ)),
) -> dict:
    tm = get_task_manager()
    tasks = await tm.get_user_tasks_async(user.id, active_only=active_only)

    if status:
        try:
            want = TaskStatus(status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Unknown status: {status}") from exc
        tasks = [t for t in tasks if t.status == want]
    if project_id is not None:
        tasks = [t for t in tasks if (t.metadata or {}).get("project_id") == str(project_id)]
    if since is not None:
        since_naive = since.replace(tzinfo=None) if since.tzinfo else since
        tasks = [t for t in tasks if t.created_at and t.created_at >= since_naive]

    total = len(tasks)
    start = (page - 1) * limit
    page_items = [_task_to_dict(t) for t in tasks[start : start + limit]]

    add_cache_headers(response, etag_source=f"tasks:{user.id}:{total}:{page}:{limit}", max_age=10)
    return paginated_response(page_items, total, page, limit)


# ---------------------------------------------------------------------------
# POST /api/v1/agents/tasks/{task_id}/cancel
# ---------------------------------------------------------------------------


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    user: User = Depends(scoped(Permission.CHAT_SEND)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tm = get_task_manager()
    task = await tm.get_task_async(task_id)
    if not task or str(task.user_id) != str(user.id):
        # Don't leak existence for tasks the caller doesn't own
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
        return {
            "task_id": task_id,
            "status": task.status.value,
            "cancel_requested": False,
            "reason": "terminal",
        }

    from ...services.pubsub import get_pubsub

    pubsub = get_pubsub()
    if pubsub is None:
        raise HTTPException(status_code=503, detail="Cancellation signal unavailable (Redis)")

    await pubsub.request_cancellation(task_id)
    await tm.update_task_status(task_id, TaskStatus.CANCELLED)

    project_id_str = (task.metadata or {}).get("project_id")
    await audit_write(
        db=db,
        user=user,
        action="agent_task.cancel",
        resource_type="agent_task",
        resource_id=None,
        project_id=UUID(project_id_str) if project_id_str else None,
        details={"task_id": task_id},
    )

    return {
        "task_id": task_id,
        "status": TaskStatus.CANCELLED.value,
        "cancel_requested": True,
        "cancelled_at": datetime.now(UTC).isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /api/v1/agents/tasks/{task_id}/steps
# ---------------------------------------------------------------------------


@router.get("/tasks/{task_id}/steps")
async def list_task_steps(
    task_id: str,
    response: Response,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(scoped(Permission.AGENTS_READ)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tm = get_task_manager()
    task = await tm.get_task_async(task_id)
    if not task or str(task.user_id) != str(user.id):
        raise HTTPException(status_code=404, detail="Task not found")

    chat_id_str = (task.metadata or {}).get("chat_id")
    if not chat_id_str:
        raise HTTPException(status_code=404, detail="Task has no associated chat")
    try:
        chat_id = UUID(chat_id_str)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Invalid chat reference") from exc

    count_stmt = select(func.count(AgentStep.id)).where(AgentStep.chat_id == chat_id)
    total = (await db.execute(count_stmt)).scalar_one() or 0

    stmt = (
        select(AgentStep)
        .where(AgentStep.chat_id == chat_id)
        .order_by(AgentStep.step_index.asc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    items = [
        {
            "id": str(s.id),
            "step_index": s.step_index,
            "step_data": s.step_data,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in rows
    ]

    add_cache_headers(response, etag_source=f"steps:{task_id}:{total}:{page}", max_age=10)
    return paginated_response(items, total, page, limit)
