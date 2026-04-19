"""
Schedules API — CRUD + lifecycle for cron-scheduled agent tasks.

Schedules are managed by the gateway process's CronScheduler, which reads
the ``agent_schedules`` table every tick.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models import AgentSchedule, Project, User
from ..services.gateway.schedule_parser import parse_schedule
from ..services.gateway.scheduler import compute_next_run
from ..users import current_active_user

router = APIRouter(prefix="/api/schedules", tags=["schedules"])
logger = logging.getLogger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ScheduleCreate(BaseModel):
    project_id: UUID
    name: str = Field(max_length=200)
    schedule: str  # Natural language or cron expression
    prompt_template: str
    agent_id: UUID | None = None
    deliver: str = "origin"
    timezone: str = "UTC"
    repeat: int | None = None
    origin_platform: str | None = None
    origin_chat_id: str | None = None
    origin_config_id: UUID | None = None


class ScheduleUpdate(BaseModel):
    name: str | None = None
    schedule: str | None = None
    prompt_template: str | None = None
    agent_id: UUID | None = None
    deliver: str | None = None
    timezone: str | None = None
    repeat: int | None = None


class ScheduleResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    cron_expression: str
    normalized_cron: str
    prompt_template: str
    timezone: str
    deliver: str
    is_active: bool
    repeat: int | None
    runs_completed: int
    last_run_at: datetime | None
    next_run_at: datetime | None
    last_status: str | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_schedule(schedule_id: UUID, user: User, db: AsyncSession) -> AgentSchedule:
    result = await db.execute(
        select(AgentSchedule).where(
            AgentSchedule.id == schedule_id,
            AgentSchedule.user_id == user.id,
        )
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.post("", response_model=ScheduleResponse)
async def create_schedule(
    payload: ScheduleCreate,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new agent schedule."""
    # Validate project access
    from ..permissions import Permission, get_project_with_access

    await get_project_with_access(db, str(payload.project_id), user.id, Permission.PROJECT_EDIT)

    # Check per-user limit
    from sqlalchemy import func

    count = await db.scalar(
        select(func.count())
        .select_from(AgentSchedule)
        .where(AgentSchedule.user_id == user.id, AgentSchedule.is_active.is_(True))
    )
    if count and count >= settings.gateway_max_schedules_per_user:
        raise HTTPException(
            status_code=429,
            detail=f"Maximum {settings.gateway_max_schedules_per_user} active schedules allowed",
        )

    # Parse schedule expression
    try:
        normalized = parse_schedule(payload.schedule)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    now = datetime.now(UTC)
    next_run = compute_next_run(normalized, after=now)

    schedule = AgentSchedule(
        user_id=user.id,
        project_id=payload.project_id,
        agent_id=payload.agent_id,
        name=payload.name,
        cron_expression=payload.schedule,
        normalized_cron=normalized,
        prompt_template=payload.prompt_template,
        timezone=payload.timezone,
        deliver=payload.deliver,
        origin_platform=payload.origin_platform,
        origin_chat_id=payload.origin_chat_id,
        origin_config_id=payload.origin_config_id,
        repeat=payload.repeat,
        next_run_at=next_run,
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)

    logger.info("[SCHEDULES] Created '%s' (id=%s, cron=%s)", payload.name, schedule.id, normalized)
    return schedule


@router.get("", response_model=list[ScheduleResponse])
async def list_schedules(
    project_id: UUID | None = Query(default=None),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List schedules for the current user, optionally filtered by project."""
    query = (
        select(AgentSchedule)
        .where(AgentSchedule.user_id == user.id)
        .order_by(AgentSchedule.created_at.desc())
    )
    if project_id:
        query = query.where(AgentSchedule.project_id == project_id)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    schedule_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single schedule."""
    return await _load_schedule(schedule_id, user, db)


@router.patch("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: UUID,
    payload: ScheduleUpdate,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a schedule."""
    schedule = await _load_schedule(schedule_id, user, db)

    if payload.name is not None:
        schedule.name = payload.name
    if payload.prompt_template is not None:
        schedule.prompt_template = payload.prompt_template
    if payload.agent_id is not None:
        schedule.agent_id = payload.agent_id
    if payload.deliver is not None:
        schedule.deliver = payload.deliver
    if payload.timezone is not None:
        schedule.timezone = payload.timezone
    if payload.repeat is not None:
        schedule.repeat = payload.repeat

    if payload.schedule is not None:
        try:
            normalized = parse_schedule(payload.schedule)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        schedule.cron_expression = payload.schedule
        schedule.normalized_cron = normalized
        schedule.next_run_at = compute_next_run(normalized)

    await db.commit()
    await db.refresh(schedule)
    return schedule


@router.delete("/{schedule_id}")
async def delete_schedule(
    schedule_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a schedule."""
    schedule = await _load_schedule(schedule_id, user, db)
    await db.delete(schedule)
    await db.commit()
    return {"status": "deleted", "id": str(schedule_id)}


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@router.post("/{schedule_id}/pause")
async def pause_schedule(
    schedule_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Pause (deactivate) a schedule."""
    schedule = await _load_schedule(schedule_id, user, db)
    schedule.is_active = False
    await db.commit()
    return {"status": "paused", "id": str(schedule_id)}


@router.post("/{schedule_id}/resume")
async def resume_schedule(
    schedule_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Resume a paused schedule and recompute next_run_at."""
    schedule = await _load_schedule(schedule_id, user, db)
    schedule.is_active = True
    schedule.next_run_at = compute_next_run(schedule.normalized_cron)
    await db.commit()
    return {"status": "resumed", "id": str(schedule_id), "next_run_at": str(schedule.next_run_at)}


@router.post("/{schedule_id}/trigger")
async def trigger_schedule(
    schedule_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a schedule immediately (test run)."""
    schedule = await _load_schedule(schedule_id, user, db)

    # Build and enqueue task directly
    import uuid as _uuid

    from ..models import Chat, Message
    from ..services.agent_task import AgentTaskPayload

    project = await db.scalar(select(Project).where(Project.id == schedule.project_id))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    task_id = str(_uuid.uuid4())

    chat = Chat(
        user_id=user.id,
        project_id=schedule.project_id,
        origin="gateway",
        title=f"[manual] {schedule.name}",
    )
    db.add(chat)
    await db.flush()

    msg = Message(chat_id=chat.id, role="user", content=schedule.prompt_template)
    db.add(msg)
    await db.commit()

    payload = AgentTaskPayload(
        task_id=task_id,
        user_id=str(user.id),
        project_id=str(schedule.project_id),
        project_slug=project.slug,
        chat_id=str(chat.id),
        message=schedule.prompt_template,
        agent_id=str(schedule.agent_id) if schedule.agent_id else None,
        gateway_deliver=schedule.deliver,
        schedule_id=str(schedule.id),
        channel_config_id=(str(schedule.origin_config_id) if schedule.origin_config_id else None),
        channel_type=schedule.origin_platform,
    )

    # Enqueue
    try:
        from ..services.task_queue import get_task_queue

        await get_task_queue().enqueue("execute_agent_task", payload.to_dict())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    schedule.last_task_id = task_id
    schedule.last_run_at = datetime.now(UTC)
    await db.commit()

    return {"status": "triggered", "task_id": task_id}
