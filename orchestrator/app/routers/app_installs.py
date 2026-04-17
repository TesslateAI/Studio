"""App Installs — install, list-mine, uninstall."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models import (
    AgentSchedule,
    AppInstance,
    AppVersion,
    Container,
    ContainerConnection,
    MarketplaceApp,
    Project,
    User,
)
from ..services.apps.installer import (
    AlreadyInstalledError,
    ConsentRejectedError,
    IncompatibleAppError,
    InstallError,
    install_app,
)
from ..services.hub_client import HubClient
from ..users import current_active_user

logger = logging.getLogger(__name__)
router = APIRouter()


class InstallRequest(BaseModel):
    app_version_id: UUID
    team_id: UUID
    wallet_mix_consent: dict[str, Any] = Field(default_factory=dict)
    mcp_consents: list[dict[str, Any]] = Field(default_factory=list)
    update_policy: str = "manual"


class InstallResponse(BaseModel):
    app_instance_id: UUID
    project_id: UUID
    volume_id: str
    node_name: str


class AppInstanceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    app_id: UUID
    app_version_id: UUID
    project_id: UUID | None = None
    state: str
    update_policy: str
    volume_id: str | None = None
    installed_at: datetime | None = None
    uninstalled_at: datetime | None = None
    created_at: datetime
    # Display fields (joined)
    app_slug: str | None = None
    app_name: str | None = None
    app_version: str | None = None


class InstallListEnvelope(BaseModel):
    items: list[AppInstanceSummary]
    total: int
    limit: int
    offset: int


class AppContainerConnectionRow(BaseModel):
    source: str
    target: str
    connector_type: str | None = None


class AppContainerRow(BaseModel):
    id: UUID
    name: str
    directory: str | None = None
    image: str | None = None
    container_type: str
    kind: str  # "base" or "service"
    port: int | None = None
    status: str
    is_primary: bool
    connections: list[AppContainerConnectionRow] = Field(default_factory=list)


class AppScheduleDetailRow(BaseModel):
    id: UUID
    name: str
    trigger_kind: str
    cron_expression: str | None = None
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    is_active: bool


class AppInstanceDetail(AppInstanceSummary):
    project_slug: str | None = None
    primary_container_id: UUID | None = None
    compute_model: str | None = None  # "always-on" | "job-only" | None
    containers: list[AppContainerRow] = Field(default_factory=list)
    schedules: list[AppScheduleDetailRow] = Field(default_factory=list)


class UninstallResponse(BaseModel):
    app_instance_id: UUID
    state: str
    uninstalled_at: datetime


def _get_hub_client() -> HubClient:
    """Dependency factory — override in tests."""
    settings = get_settings()
    return HubClient(settings.volume_hub_address)


@router.post("/install", response_model=InstallResponse, status_code=status.HTTP_201_CREATED)
async def install_endpoint(
    payload: InstallRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
    hub_client: HubClient = Depends(_get_hub_client),
) -> InstallResponse:
    try:
        try:
            result = await install_app(
                db,
                installer_user_id=user.id,
                app_version_id=payload.app_version_id,
                hub_client=hub_client,
                wallet_mix_consent=payload.wallet_mix_consent,
                mcp_consents=payload.mcp_consents,
                team_id=payload.team_id,
                update_policy=payload.update_policy,
            )
            await db.commit()
        except AlreadyInstalledError as e:
            await db.rollback()
            raise HTTPException(status_code=409, detail=str(e)) from e
        except IncompatibleAppError as e:
            await db.rollback()
            raise HTTPException(status_code=422, detail=str(e)) from e
        except ConsentRejectedError as e:
            await db.rollback()
            raise HTTPException(status_code=422, detail=str(e)) from e
        except InstallError as e:
            await db.rollback()
            raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        close = getattr(hub_client, "close", None)
        if callable(close):
            try:
                await close()
            except Exception:  # pragma: no cover
                logger.debug("hub_client close failed", exc_info=True)

    return InstallResponse(
        app_instance_id=result.app_instance_id,
        project_id=result.project_id,
        volume_id=result.volume_id,
        node_name=result.node_name,
    )


@router.get("/mine", response_model=InstallListEnvelope)
async def list_my_installs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> InstallListEnvelope:
    base = (
        select(
            AppInstance,
            MarketplaceApp.slug,
            MarketplaceApp.name,
            AppVersion.version,
        )
        .join(MarketplaceApp, MarketplaceApp.id == AppInstance.app_id)
        .join(AppVersion, AppVersion.id == AppInstance.app_version_id)
        .where(
            AppInstance.installer_user_id == user.id,
            AppInstance.state != "uninstalled",
        )
    )
    count_stmt = (
        select(func.count())
        .select_from(AppInstance)
        .where(
            AppInstance.installer_user_id == user.id,
            AppInstance.state != "uninstalled",
        )
    )
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = base.order_by(AppInstance.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).all()

    items: list[AppInstanceSummary] = []
    for inst, slug, name, version in rows:
        # Build from columns only — don't use model_validate/from_attributes,
        # which would trigger a lazy-load of AppInstance.app_version
        # (the relationship shadows the pydantic field of the same name).
        summary = AppInstanceSummary(
            id=inst.id,
            app_id=inst.app_id,
            app_version_id=inst.app_version_id,
            project_id=inst.project_id,
            state=inst.state,
            update_policy=inst.update_policy,
            volume_id=inst.volume_id,
            installed_at=inst.installed_at,
            uninstalled_at=inst.uninstalled_at,
            created_at=inst.created_at,
            app_slug=slug,
            app_name=name,
            app_version=version,
        )
        items.append(summary)

    return InstallListEnvelope(
        items=items,
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.get("/{app_instance_id}", response_model=AppInstanceDetail)
async def get_install_detail(
    app_instance_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> AppInstanceDetail:
    """Detail view: AppInstance summary + containers + connections + schedules.

    Used by the Apps Dashboard's per-card "Details" drawer. Read-only;
    lifecycle mutations remain on ``app_runtime_status``.
    """
    row = (
        await db.execute(
            select(
                AppInstance,
                MarketplaceApp.slug,
                MarketplaceApp.name,
                AppVersion.version,
                AppVersion.manifest_json,
            )
            .join(MarketplaceApp, MarketplaceApp.id == AppInstance.app_id)
            .join(AppVersion, AppVersion.id == AppInstance.app_version_id)
            .where(AppInstance.id == app_instance_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="app_instance not found")
    inst, slug, name, version, manifest_json = row

    # Auth: installer always; team members with PROJECT_EDIT on the underlying
    # project; superuser. Mirrors app_runtime_status._authorize.
    if inst.installer_user_id != user.id and not getattr(user, "is_superuser", False):
        if inst.project_id is None:
            raise HTTPException(status_code=404, detail="app_instance not found")
        from ..permissions import (
            Permission,
            get_effective_project_role,
            has_permission,
        )

        project_for_auth = await db.get(Project, inst.project_id)
        if project_for_auth is None:
            raise HTTPException(status_code=404, detail="app_instance not found")
        role = await get_effective_project_role(db, project_for_auth, user.id)
        if role is None or not has_permission(role, Permission.PROJECT_EDIT):
            raise HTTPException(status_code=404, detail="app_instance not found")

    project_slug: str | None = None
    containers_out: list[AppContainerRow] = []
    schedules_out: list[AppScheduleDetailRow] = []

    if inst.project_id is not None:
        project = await db.get(Project, inst.project_id)
        project_slug = project.slug if project else None

        containers = (
            (
                await db.execute(
                    select(Container)
                    .where(Container.project_id == inst.project_id)
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
                        ContainerConnection.project_id == inst.project_id
                    )
                )
            )
            .scalars()
            .all()
        )
        # Build a name lookup so connections can refer to containers by name
        # (matches manifest semantics) even when the FE only has IDs.
        by_id = {c.id: c for c in containers}
        for c in containers:
            kind = "service" if (c.container_type or "base") == "service" else "base"
            cxn_rows: list[AppContainerConnectionRow] = []
            for cn in connections:
                if cn.source_container_id != c.id:
                    continue
                tgt = by_id.get(cn.target_container_id)
                cxn_rows.append(
                    AppContainerConnectionRow(
                        source=c.name,
                        target=tgt.name if tgt else str(cn.target_container_id),
                        connector_type=cn.connector_type,
                    )
                )
            containers_out.append(
                AppContainerRow(
                    id=c.id,
                    name=c.name,
                    directory=c.directory,
                    image=c.image,
                    container_type=c.container_type or "base",
                    kind=kind,
                    port=c.port,
                    status=c.status or "stopped",
                    is_primary=bool(c.is_primary),
                    connections=cxn_rows,
                )
            )

        sched_rows = (
            (
                await db.execute(
                    select(AgentSchedule)
                    .where(AgentSchedule.app_instance_id == app_instance_id)
                    .order_by(AgentSchedule.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        for s in sched_rows:
            schedules_out.append(
                AppScheduleDetailRow(
                    id=s.id,
                    name=s.name,
                    trigger_kind=s.trigger_kind,
                    cron_expression=s.cron_expression,
                    next_run_at=s.next_run_at,
                    last_run_at=s.last_run_at,
                    is_active=bool(s.is_active),
                )
            )

    # Manifest compute.model — used by the FE to know whether to expect an
    # always-on surface or hide Start/Stop in favour of Schedules.
    compute_model: str | None = None
    if isinstance(manifest_json, dict):
        compute = manifest_json.get("compute")
        if isinstance(compute, dict):
            model = compute.get("model")
            if isinstance(model, str):
                compute_model = model

    return AppInstanceDetail(
        id=inst.id,
        app_id=inst.app_id,
        app_version_id=inst.app_version_id,
        project_id=inst.project_id,
        state=inst.state,
        update_policy=inst.update_policy,
        volume_id=inst.volume_id,
        installed_at=inst.installed_at,
        uninstalled_at=inst.uninstalled_at,
        created_at=inst.created_at,
        app_slug=slug,
        app_name=name,
        app_version=version,
        project_slug=project_slug,
        primary_container_id=inst.primary_container_id,
        compute_model=compute_model,
        containers=containers_out,
        schedules=schedules_out,
    )


@router.post("/{app_instance_id}/uninstall", response_model=UninstallResponse)
async def uninstall_endpoint(
    app_instance_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> UninstallResponse:
    inst = (
        await db.execute(select(AppInstance).where(AppInstance.id == app_instance_id))
    ).scalar_one_or_none()
    if inst is None:
        raise HTTPException(status_code=404, detail="app_instance not found")
    if inst.installer_user_id != user.id and not user.is_superuser:
        raise HTTPException(status_code=404, detail="app_instance not found")
    if inst.state == "uninstalled":
        raise HTTPException(status_code=409, detail="already uninstalled")

    # Capture project_id before we null it out on the instance — the K8s
    # namespace is keyed by project_id and we need it for the cleanup call.
    project_id_for_cleanup = inst.project_id

    now = datetime.now(timezone.utc)
    inst.state = "uninstalled"
    inst.uninstalled_at = now
    # Release the partial UNIQUE on project_id so the project slot is free.
    inst.project_id = None
    await db.flush()
    await db.commit()

    # Best-effort K8s cleanup. DB is the source of truth; if this fails the
    # orphan-namespace reaper will eventually clean up. Non-blocking so a
    # slow K8s API doesn't block the user's uninstall click.
    if project_id_for_cleanup is not None:
        try:
            from ..services.orchestration import get_orchestrator

            orchestrator = get_orchestrator()
            await orchestrator.delete_project_namespace(
                project_id_for_cleanup, user.id
            )
        except Exception:
            logger.exception(
                "uninstall: namespace cleanup failed for project=%s (continuing)",
                project_id_for_cleanup,
            )

    return UninstallResponse(
        app_instance_id=inst.id,
        state=inst.state,
        uninstalled_at=now,
    )
