"""App runtime status + lifecycle endpoints.

These endpoints sit in front of the same orchestrator used by regular
user projects (``KubernetesOrchestrator.start_project``) — they just
resolve the underlying Project via the AppInstance and apply the
app-centric auth model (installer or project editor).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..database import get_db
from ..models import (
    AgentSchedule,
    AppInstance,
    Container,
    ContainerConnection,
    Project,
    ScheduleTriggerEvent,
    User,
)
from ..permissions import Permission, get_effective_project_role, has_permission
from ..services.apps.runtime_urls import container_url
from ..users import current_active_user

logger = logging.getLogger(__name__)
router = APIRouter()


# --- Response shapes --------------------------------------------------------


class ContainerRuntime(BaseModel):
    id: UUID
    name: str
    status: str
    url: str | None = None


class RuntimeStatus(BaseModel):
    state: str  # stopped | starting | running | error
    primary_url: str | None = None
    project_id: UUID
    project_slug: str
    containers: list[ContainerRuntime]


# --- Helpers ----------------------------------------------------------------


async def _load_instance(db: AsyncSession, instance_id: UUID) -> AppInstance:
    inst = (
        await db.execute(select(AppInstance).where(AppInstance.id == instance_id))
    ).scalar_one_or_none()
    if inst is None:
        raise HTTPException(status_code=404, detail="app_instance not found")
    if inst.project_id is None:
        raise HTTPException(
            status_code=409,
            detail="app_instance has no project (uninstalled?)",
        )
    return inst


async def _authorize(db: AsyncSession, inst: AppInstance, user: User) -> Project:
    project = await db.get(Project, inst.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    # Installer always has access; otherwise require PROJECT_EDIT on the
    # underlying project (owner / admin / editor for team projects).
    if inst.installer_user_id == user.id or getattr(user, "is_superuser", False):
        return project
    role = await get_effective_project_role(db, project, user.id)
    if role is None or not has_permission(role, Permission.PROJECT_EDIT):
        raise HTTPException(status_code=404, detail="app_instance not found")
    return project


def _rollup_state(containers: list[Container]) -> str:
    if not containers:
        return "stopped"
    statuses = [c.status or "stopped" for c in containers]
    if any(s == "failed" for s in statuses):
        return "error"
    if any(s in {"starting", "creating"} for s in statuses):
        return "starting"
    if all(s == "running" for s in statuses):
        return "running"
    return "stopped"


def _build_runtime_payload(
    project: Project,
    containers: list[Container],
    primary_container_id: UUID | None,
) -> RuntimeStatus:
    settings = get_settings()
    protocol = settings.k8s_container_url_protocol
    domain = settings.app_domain

    primary_url: str | None = None
    items: list[ContainerRuntime] = []

    # Resolve primary first (fall back to first container).
    primary: Container | None = None
    if primary_container_id is not None:
        primary = next((c for c in containers if c.id == primary_container_id), None)
    if primary is None and containers:
        primary = next((c for c in containers if c.is_primary), None) or containers[0]

    for c in containers:
        # Use directory when present (matches ingress creation in
        # compute_manager), falling back to sanitized name for service
        # containers that historically lacked a directory.
        dir_or_name = c.directory or c.name
        url = container_url(
            project_slug=project.slug,
            container_dir_or_name=dir_or_name,
            app_domain=domain,
            protocol=protocol,
        )
        items.append(
            ContainerRuntime(id=c.id, name=c.name, status=c.status or "stopped", url=url)
        )
        if primary is not None and c.id == primary.id:
            primary_url = url

    return RuntimeStatus(
        state=_rollup_state(containers),
        primary_url=primary_url,
        project_id=project.id,
        project_slug=project.slug,
        containers=items,
    )


async def _load_project_graph(
    db: AsyncSession, project_id: UUID
) -> tuple[list[Container], list[ContainerConnection]]:
    containers = (
        (
            await db.execute(
                select(Container)
                .where(Container.project_id == project_id)
                .options(selectinload(Container.base))
                .order_by(Container.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    connections = (
        (
            await db.execute(
                select(ContainerConnection).where(
                    ContainerConnection.project_id == project_id
                )
            )
        )
        .scalars()
        .all()
    )
    return list(containers), list(connections)


# --- Endpoints --------------------------------------------------------------


@router.get("/{instance_id}/runtime", response_model=RuntimeStatus)
async def get_runtime(
    instance_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> RuntimeStatus:
    inst = await _load_instance(db, instance_id)
    project = await _authorize(db, inst, user)
    containers, _ = await _load_project_graph(db, project.id)
    return _build_runtime_payload(project, containers, inst.primary_container_id)


@router.post("/{instance_id}/start", status_code=status.HTTP_202_ACCEPTED)
async def start_runtime(
    instance_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> dict[str, Any]:
    inst = await _load_instance(db, instance_id)
    project = await _authorize(db, inst, user)
    containers, connections = await _load_project_graph(db, project.id)

    if not containers:
        raise HTTPException(
            status_code=409,
            detail="app_instance has no containers to start",
        )

    # Short-circuit: if already all-running, skip the orchestrator call.
    current = _build_runtime_payload(project, containers, inst.primary_container_id)
    if current.state in {"running", "starting"}:
        return current.model_dump(mode="json")

    from ..services.orchestration import get_orchestrator

    orchestrator = get_orchestrator()
    try:
        await orchestrator.start_project(project, containers, connections, user.id, db)
    except Exception as e:
        logger.exception(
            "app_runtime_status: start_project failed for instance=%s project=%s",
            inst.id,
            project.id,
        )
        raise HTTPException(status_code=500, detail=f"failed to start app: {e}") from e

    # Reload container statuses post-start.
    containers, _ = await _load_project_graph(db, project.id)
    return _build_runtime_payload(project, containers, inst.primary_container_id).model_dump(
        mode="json"
    )


# --- Schedules (Thread D) ---------------------------------------------------


class ScheduleRow(BaseModel):
    id: UUID
    name: str
    cron: str | None = None
    trigger_kind: str
    last_run_at: Any | None = None
    last_status: str | None = None
    enabled: bool


class SchedulePatch(BaseModel):
    enabled: bool | None = None


class TriggerEnqueued(BaseModel):
    event_id: UUID
    status: str


def _schedule_to_row(s: AgentSchedule) -> ScheduleRow:
    return ScheduleRow(
        id=s.id,
        name=s.name,
        cron=s.cron_expression,
        trigger_kind=s.trigger_kind,
        last_run_at=s.last_run_at,
        last_status=s.last_status,
        enabled=bool(s.is_active),
    )


@router.get("/{instance_id}/schedules", response_model=list[ScheduleRow])
async def list_schedules(
    instance_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> list[ScheduleRow]:
    inst = await _load_instance(db, instance_id)
    await _authorize(db, inst, user)
    rows = (
        await db.execute(
            select(AgentSchedule)
            .where(AgentSchedule.app_instance_id == instance_id)
            .order_by(AgentSchedule.created_at.asc())
        )
    ).scalars().all()
    return [_schedule_to_row(s) for s in rows]


@router.patch(
    "/{instance_id}/schedules/{schedule_id}", response_model=ScheduleRow
)
async def patch_schedule(
    instance_id: UUID,
    schedule_id: UUID,
    body: SchedulePatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> ScheduleRow:
    inst = await _load_instance(db, instance_id)
    await _authorize(db, inst, user)
    sched = (
        await db.execute(
            select(AgentSchedule).where(
                AgentSchedule.id == schedule_id,
                AgentSchedule.app_instance_id == instance_id,
            )
        )
    ).scalar_one_or_none()
    if sched is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    if body.enabled is not None:
        sched.is_active = body.enabled
    await db.commit()
    await db.refresh(sched)
    return _schedule_to_row(sched)


@router.post(
    "/{instance_id}/schedules/{schedule_id}/trigger",
    response_model=TriggerEnqueued,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_schedule_manually(
    instance_id: UUID,
    schedule_id: UUID,
    payload: dict[str, Any] | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> TriggerEnqueued:
    """Manual "Run now" — inserts a ScheduleTriggerEvent directly.

    Authenticated UI call; the HMAC check lives on the public webhook path.
    """
    import uuid as _uuid
    from datetime import datetime as _dt, timezone as _tz

    inst = await _load_instance(db, instance_id)
    await _authorize(db, inst, user)
    sched = (
        await db.execute(
            select(AgentSchedule).where(
                AgentSchedule.id == schedule_id,
                AgentSchedule.app_instance_id == instance_id,
            )
        )
    ).scalar_one_or_none()
    if sched is None:
        raise HTTPException(status_code=404, detail="schedule not found")

    event = ScheduleTriggerEvent(
        id=_uuid.uuid4(),
        schedule_id=sched.id,
        payload=payload or {},
        received_at=_dt.now(tz=_tz.utc),
    )
    db.add(event)
    await db.commit()
    logger.info(
        "app_runtime_status.trigger_schedule_manually schedule=%s event=%s user=%s",
        schedule_id, event.id, user.id,
    )
    return TriggerEnqueued(event_id=event.id, status="enqueued")


@router.post("/{instance_id}/stop")
async def stop_runtime(
    instance_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> dict[str, Any]:
    inst = await _load_instance(db, instance_id)
    project = await _authorize(db, inst, user)

    from ..services.orchestration import get_orchestrator

    orchestrator = get_orchestrator()
    try:
        await orchestrator.stop_project(project.slug, project.id, user.id)
    except Exception as e:
        logger.exception(
            "app_runtime_status: stop_project failed for instance=%s project=%s",
            inst.id,
            project.id,
        )
        raise HTTPException(status_code=500, detail=f"failed to stop app: {e}") from e

    containers, _ = await _load_project_graph(db, project.id)
    return _build_runtime_payload(project, containers, inst.primary_container_id).model_dump(
        mode="json"
    )
