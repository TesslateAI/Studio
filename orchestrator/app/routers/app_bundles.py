"""Wave 3 router: AppBundle CRUD + install. Thin layer over
`services.apps.bundles` and `services.apps.installer`."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models import AppBundle, User
from ..services.apps import bundles as bundles_svc
from ..services.apps import installer as installer_svc
from ..services.hub_client import HubClient
from ..users import current_active_user, current_superuser

logger = logging.getLogger(__name__)
router = APIRouter()

_M = ConfigDict(from_attributes=True)


class BundleItemIn(BaseModel):
    model_config = _M
    app_version_id: UUID
    order_index: int = 0
    default_enabled: bool = True
    required: bool = False


class CreateBundleRequest(BaseModel):
    slug: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=256)
    items: list[BundleItemIn] = Field(..., min_length=1)
    summary: str | None = None
    description: str | None = None


class CreateBundleResponse(BaseModel):
    bundle_id: UUID


class YankBundleRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1024)


class BundleItemOut(BaseModel):
    model_config = _M
    app_version_id: UUID
    order_index: int
    default_enabled: bool
    required: bool


class BundleOut(BaseModel):
    model_config = _M
    id: UUID
    slug: str
    display_name: str
    status: str
    consolidated_manifest_hash: str | None = None
    items: list[BundleItemOut] = Field(default_factory=list)


class BundleListItem(BaseModel):
    model_config = _M
    id: UUID
    slug: str
    display_name: str
    status: str
    owner_user_id: UUID | None


class BundleListResponse(BaseModel):
    items: list[BundleListItem]
    total: int
    limit: int
    offset: int


class BundleInstallItem(BaseModel):
    app_version_id: UUID
    wallet_mix_consent: dict[str, Any] = Field(default_factory=dict)
    mcp_consents: list[dict[str, Any]] = Field(default_factory=list)


class BundleInstallRequest(BaseModel):
    team_id: UUID
    installs: list[BundleInstallItem] = Field(..., min_length=1)


class InstalledItem(BaseModel):
    app_version_id: UUID
    app_instance_id: UUID
    project_id: UUID


class FailedItem(BaseModel):
    app_version_id: UUID
    error: str


class BundleInstallResponse(BaseModel):
    succeeded: list[InstalledItem]
    failed: list[FailedItem]
    note: str | None = None


def _is_admin(user: User) -> bool:
    return bool(getattr(user, "is_superuser", False))


@router.post("", response_model=CreateBundleResponse, status_code=201)
async def create_bundle_endpoint(
    body: CreateBundleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
) -> CreateBundleResponse:
    specs = [
        bundles_svc.BundleItemSpec(
            app_version_id=i.app_version_id,
            order_index=i.order_index,
            default_enabled=i.default_enabled,
            required=i.required,
        )
        for i in body.items
    ]
    try:
        bid = await bundles_svc.create_bundle(
            db,
            owner_user_id=current_user.id,
            slug=body.slug,
            display_name=body.display_name,
            items=specs,
            summary=body.summary,
            description=body.description,
        )
    except bundles_svc.BundleSlugTakenError:
        raise HTTPException(status_code=409, detail=f"slug '{body.slug}' is taken") from None
    except bundles_svc.BundleError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return CreateBundleResponse(bundle_id=bid)


@router.get("", response_model=BundleListResponse)
async def list_bundles_endpoint(
    owner_user_id: UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
) -> BundleListResponse:
    stmt = select(AppBundle)
    if _is_admin(current_user):
        if owner_user_id is not None:
            stmt = stmt.where(AppBundle.owner_user_id == owner_user_id)
    else:
        effective = owner_user_id or current_user.id
        if effective != current_user.id:
            raise HTTPException(status_code=403, detail="cannot list other users' bundles")
        stmt = stmt.where(AppBundle.owner_user_id == effective)
    if status_filter is not None:
        if status_filter not in {"draft", "approved", "yanked"}:
            raise HTTPException(status_code=400, detail="invalid status filter")
        stmt = stmt.where(AppBundle.status == status_filter)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (await db.execute(stmt.order_by(AppBundle.created_at.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    return BundleListResponse(
        items=[BundleListItem.model_validate(r) for r in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.get("/{bundle_id}", response_model=BundleOut)
async def get_bundle_endpoint(
    bundle_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
) -> BundleOut:
    header = (
        await db.execute(select(AppBundle).where(AppBundle.id == bundle_id))
    ).scalar_one_or_none()
    if header is None:
        raise HTTPException(status_code=404, detail="bundle not found")
    if not (
        header.owner_user_id == current_user.id
        or _is_admin(current_user)
        or header.status == "approved"
    ):
        raise HTTPException(status_code=404, detail="bundle not found")
    try:
        data = await bundles_svc.get_bundle(db, bundle_id=bundle_id)
    except bundles_svc.BundleNotFoundError:
        raise HTTPException(status_code=404, detail="bundle not found") from None
    return BundleOut(**data)


@router.post("/{bundle_id}/publish", status_code=204)
async def publish_bundle_endpoint(
    bundle_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_superuser),
) -> Response:
    try:
        await bundles_svc.publish_bundle(db, bundle_id=bundle_id, actor_user_id=current_user.id)
    except bundles_svc.BundleNotFoundError:
        raise HTTPException(status_code=404, detail="bundle not found") from None
    except bundles_svc.BundleError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return Response(status_code=204)


@router.post("/{bundle_id}/yank", status_code=204)
async def yank_bundle_endpoint(
    bundle_id: UUID,
    body: YankBundleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_superuser),
) -> Response:
    try:
        await bundles_svc.yank_bundle(
            db,
            bundle_id=bundle_id,
            actor_user_id=current_user.id,
            reason=body.reason,
        )
    except bundles_svc.BundleNotFoundError:
        raise HTTPException(status_code=404, detail="bundle not found") from None
    except bundles_svc.BundleError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return Response(status_code=204)


@router.post("/{bundle_id}/install")
async def install_bundle_endpoint(
    bundle_id: UUID,
    body: BundleInstallRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
) -> BundleInstallResponse:
    try:
        bundle = await bundles_svc.get_bundle(db, bundle_id=bundle_id)
    except bundles_svc.BundleNotFoundError:
        raise HTTPException(status_code=404, detail="bundle not found") from None
    consents_by_av = {i.app_version_id: i for i in body.installs}
    hub = HubClient(get_settings().volume_hub_address)
    succeeded: list[InstalledItem] = []
    failed: list[FailedItem] = []
    # Wave 3 stub: best-effort iteration; earlier successes are NOT rolled
    # back if a later install fails. Callers must inspect `failed` on 207.
    for item in bundle["items"]:
        if not item["default_enabled"]:
            continue
        av_id: UUID = item["app_version_id"]
        consent = consents_by_av.get(av_id)
        if consent is None:
            failed.append(FailedItem(app_version_id=av_id, error="no consent payload supplied"))
            continue
        try:
            result = await installer_svc.install_app(
                db,
                installer_user_id=current_user.id,
                app_version_id=av_id,
                hub_client=hub,
                wallet_mix_consent=consent.wallet_mix_consent,
                mcp_consents=consent.mcp_consents,
                team_id=body.team_id,
            )
            succeeded.append(
                InstalledItem(
                    app_version_id=av_id,
                    app_instance_id=result.app_instance_id,
                    project_id=result.project_id,
                )
            )
        except installer_svc.InstallError as e:
            failed.append(FailedItem(app_version_id=av_id, error=str(e)))
        except Exception as e:  # defensive
            logger.exception("bundle install: unexpected failure for av=%s", av_id)
            failed.append(FailedItem(app_version_id=av_id, error=repr(e)))
    note: str | None = None
    if failed:
        response.status_code = status.HTTP_207_MULTI_STATUS
        note = (
            "partial success; earlier installs were NOT rolled back"
            if succeeded
            else "all items failed"
        )
    else:
        response.status_code = status.HTTP_200_OK
    return BundleInstallResponse(succeeded=succeeded, failed=failed, note=note)
