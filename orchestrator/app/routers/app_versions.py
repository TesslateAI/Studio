"""App Versions — publish + inspect a single version."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models import AppVersion, MarketplaceApp, User
from ..services.apps import compatibility
from ..services.apps.manifest_parser import ManifestValidationError
from ..services.apps.publisher import (
    CompatibilityError,
    DuplicateVersionError,
    PublishError,
    SourceNotPublishableError,
    publish_version,
)
from ..services.hub_client import HubClient
from ..users import current_active_user

logger = logging.getLogger(__name__)
router = APIRouter()


class PublishRequest(BaseModel):
    project_id: UUID
    manifest: Any  # str | dict — passed through to publisher
    app_id: UUID | None = None


class PublishResponse(BaseModel):
    app_id: UUID
    app_version_id: UUID
    version: str
    bundle_hash: str
    manifest_hash: str
    submission_id: UUID


class AppVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    app_id: UUID
    version: str
    manifest_schema_version: str
    manifest_json: dict[str, Any] | None = None
    manifest_hash: str
    bundle_hash: str | None = None
    feature_set_hash: str
    required_features: list[str] = []
    approval_state: str
    yanked_at: datetime | None = None
    yanked_reason: str | None = None
    yanked_is_critical: bool = False
    published_at: datetime | None = None
    created_at: datetime


class CompatReportResponse(BaseModel):
    compatible: bool
    missing_features: list[str]
    unsupported_manifest_schema: bool
    upgrade_required: bool
    server_manifest_schemas: list[str]
    server_feature_set_hash: str


def _get_hub_client() -> HubClient:
    """Dependency factory — override in tests."""
    settings = get_settings()
    return HubClient(settings.volume_hub_address)


@router.post("/publish", response_model=PublishResponse, status_code=status.HTTP_201_CREATED)
async def publish_endpoint(
    payload: PublishRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
    hub_client: HubClient = Depends(_get_hub_client),
) -> PublishResponse:
    try:
        try:
            result = await publish_version(
                db,
                creator_user_id=user.id,
                project_id=payload.project_id,
                manifest_source=payload.manifest,
                hub_client=hub_client,
                app_id=payload.app_id,
            )
            await db.commit()
        except ManifestValidationError as e:
            await db.rollback()
            raise HTTPException(status_code=422, detail=f"manifest invalid: {e}") from e
        except SourceNotPublishableError as e:
            await db.rollback()
            raise HTTPException(status_code=422, detail=str(e)) from e
        except CompatibilityError as e:
            await db.rollback()
            raise HTTPException(status_code=422, detail=str(e)) from e
        except DuplicateVersionError as e:
            await db.rollback()
            raise HTTPException(status_code=409, detail=str(e)) from e
        except PublishError as e:
            await db.rollback()
            raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        # Best-effort: close the grpc channel if one was opened.
        close = getattr(hub_client, "close", None)
        if callable(close):
            try:
                await close()
            except Exception:  # pragma: no cover
                logger.debug("hub_client close failed", exc_info=True)

    return PublishResponse(
        app_id=result.app_id,
        app_version_id=result.app_version_id,
        version=result.version,
        bundle_hash=result.bundle_hash,
        manifest_hash=result.manifest_hash,
        submission_id=result.submission_id,
    )


@router.get("/{app_version_id}", response_model=AppVersionResponse)
async def get_app_version(
    app_version_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> AppVersionResponse:
    version_row = (
        await db.execute(select(AppVersion).where(AppVersion.id == app_version_id))
    ).scalar_one_or_none()
    if version_row is None:
        raise HTTPException(status_code=404, detail="app_version not found")

    app_row = (
        await db.execute(
            select(MarketplaceApp).where(MarketplaceApp.id == version_row.app_id)
        )
    ).scalar_one_or_none()
    if app_row is None:
        raise HTTPException(status_code=404, detail="app not found")

    is_owner_or_admin = user.is_superuser or app_row.creator_user_id == user.id
    is_public = app_row.visibility == "public" and app_row.state == "approved"

    if not (is_owner_or_admin or is_public):
        raise HTTPException(status_code=404, detail="app_version not found")

    resp = AppVersionResponse.model_validate(version_row)
    # Hide manifest_json for non-owners on non-public apps (belt + suspenders).
    if not is_owner_or_admin and app_row.visibility != "public":
        resp = resp.model_copy(update={"manifest_json": None})
    return resp


@router.get("/{app_version_id}/compat", response_model=CompatReportResponse)
async def check_app_version_compat(
    app_version_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> CompatReportResponse:
    version_row = (
        await db.execute(select(AppVersion).where(AppVersion.id == app_version_id))
    ).scalar_one_or_none()
    if version_row is None:
        raise HTTPException(status_code=404, detail="app_version not found")

    manifest = version_row.manifest_json or {}
    manifest_schema = (
        manifest.get("compatibility", {}).get("manifest_schema")
        or manifest.get("manifest_schema_version")
        or version_row.manifest_schema_version
        or ""
    )
    report = compatibility.check(
        required_features=list(version_row.required_features or []),
        manifest_schema=manifest_schema,
    )
    return CompatReportResponse(
        compatible=report.compatible,
        missing_features=report.missing_features,
        unsupported_manifest_schema=report.unsupported_manifest_schema,
        upgrade_required=report.upgrade_required,
        server_manifest_schemas=report.server_manifest_schemas,
        server_feature_set_hash=report.server_feature_set_hash,
    )
