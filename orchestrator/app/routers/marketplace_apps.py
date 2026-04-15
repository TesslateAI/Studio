"""Marketplace Apps — browse, inspect, fork."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import AppInstance, AppVersion, MarketplaceApp, User
from ..config import get_settings
from ..services.apps.fork import ForkError, NotForkableError, fork_app
from ..services.hub_client import HubClient
from ..users import current_active_user

logger = logging.getLogger(__name__)
router = APIRouter()


class MarketplaceAppResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    description: str | None = None
    category: str | None = None
    icon_ref: str | None = None
    forkable: str
    forked_from: UUID | None = None
    visibility: str
    state: str
    reputation: dict[str, Any] = Field(default_factory=dict)
    creator_user_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class AppVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    app_id: UUID
    version: str
    manifest_schema_version: str
    manifest_hash: str
    bundle_hash: str | None = None
    approval_state: str
    yanked_at: datetime | None = None
    yanked_reason: str | None = None
    yanked_is_critical: bool = False
    published_at: datetime | None = None
    created_at: datetime


class AppListEnvelope(BaseModel):
    items: list[MarketplaceAppResponse]
    total: int
    limit: int
    offset: int


class AppVersionListEnvelope(BaseModel):
    items: list[AppVersionSummary]
    total: int
    limit: int
    offset: int


class ForkRequest(BaseModel):
    source_app_version_id: UUID
    new_slug: str
    new_name: str
    team_id: UUID | None = None


class ForkResponse(MarketplaceAppResponse):
    project_id: UUID | None = None
    project_slug: str | None = None


def _get_hub_client() -> HubClient:
    settings = get_settings()
    return HubClient(settings.volume_hub_address)


async def _user_can_see_app(
    db: AsyncSession, app_row: MarketplaceApp, user: User
) -> bool:
    if user.is_superuser:
        return True
    if app_row.creator_user_id == user.id:
        return True
    if app_row.visibility == "public" and app_row.state == "approved":
        return True
    # Installer with an instance can see the app row.
    inst_id = (
        await db.execute(
            select(AppInstance.id)
            .where(
                AppInstance.app_id == app_row.id,
                AppInstance.installer_user_id == user.id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return inst_id is not None


@router.get("", response_model=AppListEnvelope)
async def list_apps(
    q: str | None = Query(None, description="Substring match on name or slug"),
    category: str | None = Query(None),
    creator_user_id: UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> AppListEnvelope:
    stmt = select(MarketplaceApp)
    count_stmt = select(func.count()).select_from(MarketplaceApp)

    filters = []
    if not user.is_superuser:
        filters.append(MarketplaceApp.visibility == "public")
        filters.append(MarketplaceApp.state == "approved")
    if q:
        pat = f"%{q}%"
        filters.append(or_(MarketplaceApp.name.ilike(pat), MarketplaceApp.slug.ilike(pat)))
    if category:
        filters.append(MarketplaceApp.category == category)
    if creator_user_id:
        filters.append(MarketplaceApp.creator_user_id == creator_user_id)

    for f in filters:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = stmt.order_by(MarketplaceApp.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return AppListEnvelope(
        items=[MarketplaceAppResponse.model_validate(r) for r in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.get("/{app_id}", response_model=MarketplaceAppResponse)
async def get_app(
    app_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> MarketplaceAppResponse:
    row = (
        await db.execute(select(MarketplaceApp).where(MarketplaceApp.id == app_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="app not found")
    if not await _user_can_see_app(db, row, user):
        raise HTTPException(status_code=404, detail="app not found")
    return MarketplaceAppResponse.model_validate(row)


@router.get("/{app_id}/versions", response_model=AppVersionListEnvelope)
async def list_app_versions(
    app_id: UUID,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> AppVersionListEnvelope:
    app_row = (
        await db.execute(select(MarketplaceApp).where(MarketplaceApp.id == app_id))
    ).scalar_one_or_none()
    if app_row is None:
        raise HTTPException(status_code=404, detail="app not found")
    if not await _user_can_see_app(db, app_row, user):
        raise HTTPException(status_code=404, detail="app not found")

    is_owner_or_admin = user.is_superuser or app_row.creator_user_id == user.id

    stmt = select(AppVersion).where(AppVersion.app_id == app_id)
    count_stmt = select(func.count()).select_from(AppVersion).where(AppVersion.app_id == app_id)
    if not is_owner_or_admin:
        stmt = stmt.where(
            AppVersion.approval_state.in_(("stage1_approved", "stage2_approved")),
            AppVersion.yanked_at.is_(None),
        )
        count_stmt = count_stmt.where(
            AppVersion.approval_state.in_(("stage1_approved", "stage2_approved")),
            AppVersion.yanked_at.is_(None),
        )

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = stmt.order_by(AppVersion.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return AppVersionListEnvelope(
        items=[AppVersionSummary.model_validate(r) for r in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{app_id}/fork",
    response_model=ForkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def fork_marketplace_app(
    app_id: UUID,
    payload: ForkRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
    hub_client: HubClient = Depends(_get_hub_client),
) -> ForkResponse:
    # Ensure the source version belongs to the declared app (caller-supplied
    # source_app_version_id is the authoritative fork root per service API).
    src = (
        await db.execute(
            select(AppVersion).where(AppVersion.id == payload.source_app_version_id)
        )
    ).scalar_one_or_none()
    if src is None or src.app_id != app_id:
        raise HTTPException(status_code=404, detail="source app_version not found for app")

    try:
        result = await fork_app(
            db,
            forker_user_id=user.id,
            source_app_version_id=payload.source_app_version_id,
            new_slug=payload.new_slug,
            new_name=payload.new_name,
            team_id=payload.team_id,
            hub_client=hub_client,
        )
        await db.commit()
    except NotForkableError as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ForkError as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e

    new_app = (
        await db.execute(select(MarketplaceApp).where(MarketplaceApp.id == result.new_app_id))
    ).scalar_one()
    base = MarketplaceAppResponse.model_validate(new_app)
    return ForkResponse(
        **base.model_dump(),
        project_id=result.project_id,
        project_slug=result.project_slug,
    )
