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
from ..models import AppInstance, AppVersion, MarketplaceApp, User
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
    project_id: UUID | None
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

    now = datetime.now(timezone.utc)
    inst.state = "uninstalled"
    inst.uninstalled_at = now
    # Release the partial UNIQUE on project_id so the project slot is free.
    inst.project_id = None
    await db.flush()
    await db.commit()

    return UninstallResponse(
        app_instance_id=inst.id,
        state=inst.state,
        uninstalled_at=now,
    )
