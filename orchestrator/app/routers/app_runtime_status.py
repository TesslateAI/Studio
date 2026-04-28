"""App runtime status + lifecycle endpoints.

These endpoints sit in front of the same orchestrator used by regular
user projects (``KubernetesOrchestrator.start_project``) — they just
resolve the underlying Project via the AppInstance and apply the
app-centric auth model (installer or project editor).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..auth import get_current_active_user_or_query
from ..config import get_settings
from ..database import get_db
from ..models import (
    AppInstance,
    Container,
    ContainerConnection,
    Project,
    User,
)
from ..models_automations import (
    AutomationDefinition,
    AutomationEvent,
    AutomationTrigger,
)
from ..permissions import Permission, get_effective_project_role, has_permission
from ..services.apps.runtime_urls import (
    app_container_url,
    container_url,
)
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
    # Headless / job-only apps: every container is invoked as a scheduled K8s
    # Job, never as a long-running Deployment. Surface this as its own state
    # so the UI can hide the iframe and direct users to the Schedules tab.
    if statuses and all(s == "job_only" for s in statuses):
        return "job_only"
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
    *,
    app_handle: str | None = None,
    creator_handle: str | None = None,
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

    # When both handles are present, all container URLs use the
    # creator-branded shape. Single-container apps collapse to
    # ``{app}-{creator}.{domain}``.
    only_primary = len(containers) <= 1
    use_app_url = bool(app_handle and creator_handle)

    # Reuse the Ingress builder's directory resolution so the UI's URL
    # always matches the hostname the Ingress was created with. Without
    # this, a container with ``directory='.'`` lands ingress under
    # ``{project_slug}-{uuid_prefix}.{domain}`` but the legacy lookup
    # ``c.directory or c.name`` evaluates ``"."`` truthy and renders
    # ``{project_slug}-..{domain}`` — DNS NXDOMAIN, no working preview.
    from ..services.compute_manager import resolve_k8s_container_dir

    for c in containers:
        dir_or_name = resolve_k8s_container_dir(c)
        if use_app_url:
            url = app_container_url(
                app_handle=app_handle,
                creator_handle=creator_handle,
                container_dir=(dir_or_name or "app").lower(),
                app_domain=domain,
                protocol=protocol,
                only_primary=only_primary and (primary is not None and c.id == primary.id),
            )
        else:
            url = container_url(
                project_slug=project.slug,
                container_dir_or_name=dir_or_name,
                app_domain=domain,
                protocol=protocol,
            )
        items.append(ContainerRuntime(id=c.id, name=c.name, status=c.status or "stopped", url=url))
        if primary is not None and c.id == primary.id:
            primary_url = url

    return RuntimeStatus(
        state=_rollup_state(containers),
        primary_url=primary_url,
        project_id=project.id,
        project_slug=project.slug,
        containers=items,
    )


async def _load_app_handles(db: AsyncSession, inst: AppInstance) -> tuple[str | None, str | None]:
    """Return ``(app_handle, creator_handle)`` for an AppInstance.

    Either may be None if the row hasn't been backfilled; the caller
    falls back to the legacy slug-based URL shape.
    """
    from ..models import MarketplaceApp

    app_row = await db.get(MarketplaceApp, inst.app_id)
    if app_row is None:
        return None, None
    app_handle = getattr(app_row, "handle", None)
    creator_handle: str | None = None
    if app_row.creator_user_id is not None:
        creator = await db.get(User, app_row.creator_user_id)
        if creator is not None:
            creator_handle = getattr(creator, "handle", None)
    return app_handle, creator_handle


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
                select(ContainerConnection).where(ContainerConnection.project_id == project_id)
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
    _app_h, _creator_h = await _load_app_handles(db, inst)
    return _build_runtime_payload(
        project, containers, inst.primary_container_id, app_handle=_app_h, creator_handle=_creator_h
    )


@router.get("/{instance_id}/events")
async def runtime_events(
    instance_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user_or_query),
) -> StreamingResponse:
    """SSE stream of app-runtime lifecycle events for an AppInstance.

    Emits an initial snapshot identical to ``GET /runtime``, then tails the
    Redis stream populated by ``compute_manager`` pod-lifecycle hooks. A
    heartbeat comment is sent every 15s to keep proxies from idling out.
    """
    inst = await _load_instance(db, instance_id)
    project = await _authorize(db, inst, user)
    containers, _ = await _load_project_graph(db, project.id)
    _app_h, _creator_h = await _load_app_handles(db, inst)
    snapshot = _build_runtime_payload(
        project, containers, inst.primary_container_id, app_handle=_app_h, creator_handle=_creator_h
    )

    async def event_stream():
        from ..services.pubsub import subscribe_app_runtime_events

        # 1. Initial snapshot (so the client can paint immediately).
        yield f"data: {snapshot.model_dump_json()}\n\n"

        # 2. Tail the Redis stream + heartbeat in parallel.
        sub = subscribe_app_runtime_events(instance_id, last_id="$")
        sub_iter = sub.__aiter__()

        next_event_task: asyncio.Task | None = None
        try:
            while True:
                if await request.is_disconnected():
                    return
                if next_event_task is None:
                    next_event_task = asyncio.create_task(sub_iter.__anext__())
                done, _pending = await asyncio.wait({next_event_task}, timeout=15.0)
                if not done:
                    # Heartbeat (SSE comment line).
                    yield ": heartbeat\n\n"
                    continue
                try:
                    _entry_id, event = next_event_task.result()
                except StopAsyncIteration:
                    return
                except Exception as e:  # noqa: BLE001
                    logger.debug("app_runtime SSE subscriber ended: %s", e)
                    return
                finally:
                    next_event_task = None
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            if next_event_task is not None and not next_event_task.done():
                next_event_task.cancel()
            # Best-effort close of the async generator.
            with contextlib.suppress(Exception):
                await sub.aclose()

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # Disable nginx response buffering for SSE.
    }
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)


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
    _app_h, _creator_h = await _load_app_handles(db, inst)
    current = _build_runtime_payload(
        project, containers, inst.primary_container_id, app_handle=_app_h, creator_handle=_creator_h
    )
    if current.state in {"running", "starting"}:
        return current.model_dump(mode="json")
    # Headless / job-only apps have no Deployments to start — schedules drive
    # everything. Return 200 with the current rollup so the UI knows to render
    # the headless surface instead of polling for "running".
    if current.state == "job_only":
        return current.model_dump(mode="json")

    # Per-user soft cap on concurrently running apps. Paused apps
    # (environment_status != "active") do NOT count. Enforced before the
    # per-project lock so tenant A's cap exhaustion cannot stall tenant B.
    settings = get_settings()
    running_cap = settings.tsl_max_running_apps_per_user
    if running_cap > 0:
        count_stmt = (
            select(func.count(AppInstance.id))
            .join(Project, Project.id == AppInstance.project_id)
            .where(
                AppInstance.installer_user_id == user.id,
                AppInstance.state == "installed",
                Project.environment_status == "active",
                AppInstance.id != inst.id,
            )
        )
        running_now = (await db.execute(count_stmt)).scalar_one()
        if running_now >= running_cap:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "max_running_apps_reached",
                    "limit": running_cap,
                    "running": running_now,
                    "message": (
                        f"You have {running_now} apps running. Stop one before "
                        f"starting another (limit: {running_cap})."
                    ),
                },
            )

    from ..services.apps.installer import create_per_pod_signing_key
    from ..services.compute_manager import current_app_instance_id
    from ..services.orchestration import get_orchestrator

    orchestrator = get_orchestrator()
    # Bind app_instance_id for downstream compute_manager so pod-lifecycle
    # transitions are fanned out to the SSE stream for this AppInstance.
    token = current_app_instance_id.set(inst.id)
    try:
        await orchestrator.start_project(project, containers, connections, user.id, db)
        # Mint the per-pod HMAC signing-key Secret AFTER the namespace
        # exists. The install router can't write this Secret because the
        # ``proj-{id}`` namespace is created here, not at install time.
        # The pod template has already rendered the env reference
        # ``${secret:app-pod-key-{instance_id}/token}``; if the pod hit
        # CreateContainerConfigError first because the Secret was missing,
        # kubelet auto-retries on Secret appearance — the pod will start
        # within seconds of this call returning.
        try:
            await create_per_pod_signing_key(
                app_instance_id=inst.id,
                target_namespace=f"proj-{project.id}",
            )
        except Exception:
            logger.warning(
                "app_runtime_status: per-pod signing-key creation failed "
                "instance=%s ns=proj-%s (proxy will fall back to "
                "deterministic-derivation key, but the pod template's "
                "secretKeyRef will fail to resolve)",
                inst.id,
                project.id,
                exc_info=True,
            )
    except RuntimeError as e:
        # Concurrent /start — another request holds the env lock and is already
        # bringing the environment up. Return the current rollup idempotently.
        if "is held by another operation" in str(e):
            logger.info(
                "app_runtime_status: start_project already in-flight for instance=%s; returning current state",
                inst.id,
            )
            containers, _ = await _load_project_graph(db, project.id)
            _app_h, _creator_h = await _load_app_handles(db, inst)
            return _build_runtime_payload(
                project,
                containers,
                inst.primary_container_id,
                app_handle=_app_h,
                creator_handle=_creator_h,
            ).model_dump(mode="json")
        logger.exception(
            "app_runtime_status: start_project failed for instance=%s project=%s",
            inst.id,
            project.id,
        )
        raise HTTPException(status_code=500, detail=f"failed to start app: {e}") from e
    except Exception as e:
        logger.exception(
            "app_runtime_status: start_project failed for instance=%s project=%s",
            inst.id,
            project.id,
        )
        raise HTTPException(status_code=500, detail=f"failed to start app: {e}") from e
    finally:
        current_app_instance_id.reset(token)

    # Reload container statuses post-start.
    containers, _ = await _load_project_graph(db, project.id)
    _app_h, _creator_h = await _load_app_handles(db, inst)
    return _build_runtime_payload(
        project, containers, inst.primary_container_id, app_handle=_app_h, creator_handle=_creator_h
    ).model_dump(mode="json")


# --- Schedules -------------------------------------------------------------


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


async def _list_instance_schedules(
    db: AsyncSession, *, target_project_id: UUID
) -> list[ScheduleRow]:
    """Project automation_definitions scoped to an install's runtime project.

    The install's automation_definitions are the ones the installer (or the
    install-time template materializer) created with
    ``target_project_id == instance.project_id``. Each row is paired with
    its first ``automation_triggers`` row to surface ``cron`` / ``kind`` to
    the existing UI shape — the legacy ``ScheduleRow`` carried a single
    ``cron`` + ``trigger_kind``, so collapsing the multi-trigger model to
    "first trigger wins" matches what the UI already renders.
    """
    rows = (
        (
            await db.execute(
                select(AutomationDefinition)
                .where(AutomationDefinition.target_project_id == target_project_id)
                .order_by(AutomationDefinition.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return []
    triggers_by_definition: dict[UUID, AutomationTrigger] = {}
    if rows:
        trigger_rows = (
            (
                await db.execute(
                    select(AutomationTrigger)
                    .where(
                        AutomationTrigger.automation_id.in_([r.id for r in rows])
                    )
                    .order_by(AutomationTrigger.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        for trig in trigger_rows:
            triggers_by_definition.setdefault(trig.automation_id, trig)

    out: list[ScheduleRow] = []
    for defn in rows:
        trig = triggers_by_definition.get(defn.id)
        cron_expr: str | None = None
        trigger_kind = "manual"
        last_run_at = None
        if trig is not None:
            trigger_kind = trig.kind
            cron_expr = (trig.config or {}).get("cron") if isinstance(trig.config, dict) else None
            last_run_at = trig.last_run_at
        out.append(
            ScheduleRow(
                id=defn.id,
                name=defn.name,
                cron=cron_expr,
                trigger_kind=trigger_kind,
                last_run_at=last_run_at,
                last_status=None,
                enabled=bool(defn.is_active),
            )
        )
    return out


@router.get("/{instance_id}/schedules", response_model=list[ScheduleRow])
async def list_schedules(
    instance_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> list[ScheduleRow]:
    inst = await _load_instance(db, instance_id)
    await _authorize(db, inst, user)
    if inst.project_id is None:
        return []
    return await _list_instance_schedules(db, target_project_id=inst.project_id)


@router.patch("/{instance_id}/schedules/{schedule_id}", response_model=ScheduleRow)
async def patch_schedule(
    instance_id: UUID,
    schedule_id: UUID,
    body: SchedulePatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> ScheduleRow:
    inst = await _load_instance(db, instance_id)
    await _authorize(db, inst, user)
    if inst.project_id is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    defn = (
        await db.execute(
            select(AutomationDefinition).where(
                AutomationDefinition.id == schedule_id,
                AutomationDefinition.target_project_id == inst.project_id,
            )
        )
    ).scalar_one_or_none()
    if defn is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    if body.enabled is not None:
        defn.is_active = body.enabled
    await db.commit()
    rows = await _list_instance_schedules(db, target_project_id=inst.project_id)
    matching = next((r for r in rows if r.id == schedule_id), None)
    if matching is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    return matching


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
    """Manual "Run now" — mints an ``AutomationEvent`` (kind=manual) and
    enqueues ``dispatch_automation_task``.

    Mirrors the manual-run path on ``/api/automations/{id}/run`` so the
    install-detail UI doesn't have to do its own dispatcher dance —
    same primitives, same ARQ queue.
    """
    inst = await _load_instance(db, instance_id)
    await _authorize(db, inst, user)
    if inst.project_id is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    defn = (
        await db.execute(
            select(AutomationDefinition).where(
                AutomationDefinition.id == schedule_id,
                AutomationDefinition.target_project_id == inst.project_id,
            )
        )
    ).scalar_one_or_none()
    if defn is None:
        raise HTTPException(status_code=404, detail="schedule not found")

    event = AutomationEvent(
        id=uuid.uuid4(),
        automation_id=defn.id,
        trigger_id=None,
        payload=payload or {},
        trigger_kind="manual",
        received_at=datetime.now(tz=UTC),
    )
    db.add(event)
    await db.commit()

    from ..task_queue import get_task_queue

    await get_task_queue().enqueue(
        "dispatch_automation_task", str(defn.id), str(event.id)
    )
    logger.info(
        "app_runtime_status.trigger_schedule_manually automation=%s event=%s user=%s",
        defn.id,
        event.id,
        user.id,
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

    # job-only apps have no Deployments to stop — return current rollup as 200.
    containers, _ = await _load_project_graph(db, project.id)
    _app_h, _creator_h = await _load_app_handles(db, inst)
    current = _build_runtime_payload(
        project, containers, inst.primary_container_id, app_handle=_app_h, creator_handle=_creator_h
    )
    if current.state == "job_only":
        return current.model_dump(mode="json")

    from ..services.compute_manager import _emit_app_runtime
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

    # Reload post-stop so we see the compute_manager's DB writes
    # (environment_status=stopped, container.status=stopped), then fan out
    # a terminal "stopped" event to any live SSE subscribers. Emit at the
    # router level (not inside compute_manager) so we don't depend on
    # ContextVar propagation through the orchestrator's fresh session.
    # expunge_all() clears the identity map so subsequent SELECT queries
    # return fresh rows (compute_manager wrote via a different session).
    db.expunge_all()
    project = await db.get(Project, project.id)
    containers, _ = await _load_project_graph(db, project.id)
    _app_h, _creator_h = await _load_app_handles(db, inst)
    await _emit_app_runtime(
        inst.id, "stopped", containers=containers, message="Environment stopped"
    )
    return _build_runtime_payload(
        project, containers, inst.primary_container_id, app_handle=_app_h, creator_handle=_creator_h
    ).model_dump(mode="json")
