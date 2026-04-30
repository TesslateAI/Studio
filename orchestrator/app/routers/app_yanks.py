"""Wave 3: Yank workflow router.

- Any authenticated user can request a yank.
- Admins approve/reject (critical severity requires a second distinct admin).
- Only the creator-owner of the underlying MarketplaceApp may file an appeal.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import AppVersion, MarketplaceApp, User, YankRequest
from ..services.apps import yanks as yanks_svc
from ..users import current_active_user, current_superuser

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class YankRequestIn(BaseModel):
    app_version_id: UUID
    severity: str  # low | medium | critical
    reason: str


class YankRequestCreatedOut(BaseModel):
    yank_request_id: UUID


class YankApproveOut(BaseModel):
    status: str
    needs_second_admin: bool = False
    primary_admin_id: UUID | None = None
    secondary_admin_id: UUID | None = None


class YankRejectIn(BaseModel):
    note: str | None = None


class YankRejectOut(BaseModel):
    status: str


class YankAppealIn(BaseModel):
    reason: str


class YankAppealOut(BaseModel):
    appeal_id: UUID


class YankOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    app_version_id: UUID
    requester_user_id: UUID | None = None
    severity: str
    reason: str
    status: str
    primary_admin_id: UUID | None = None
    secondary_admin_id: UUID | None = None


class YankListOut(BaseModel):
    items: list[YankOut]
    limit: int
    offset: int
    total: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=YankRequestCreatedOut)
async def create_yank(
    body: YankRequestIn,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> YankRequestCreatedOut:
    yid = await yanks_svc.request_yank(
        db,
        requester_user_id=user.id,
        app_version_id=body.app_version_id,
        severity=body.severity,  # type: ignore[arg-type]
        reason=body.reason,
    )
    # Service only flushes; commit so the yank row persists past request teardown.
    await db.commit()
    return YankRequestCreatedOut(yank_request_id=yid)


@router.post("/{yank_request_id}/approve", response_model=YankApproveOut)
async def approve(
    yank_request_id: UUID,
    user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> YankApproveOut:
    try:
        result = await yanks_svc.approve_yank(
            db, yank_request_id=yank_request_id, admin_user_id=user.id
        )
    except yanks_svc.NeedsSecondAdminError:
        raise HTTPException(status_code=409, detail="second admin required") from None
    except yanks_svc.AlreadyDecidedError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except yanks_svc.YankNotFoundError:
        raise HTTPException(status_code=404, detail="yank not found") from None
    await db.commit()

    # Reload for admin ids to mirror back to caller.
    row = (
        await db.execute(select(YankRequest).where(YankRequest.id == yank_request_id))
    ).scalar_one_or_none()
    primary = row.primary_admin_id if row is not None else None
    secondary = row.secondary_admin_id if row is not None else None

    if "needs_second_admin" in result and result.get("needs_second_admin"):
        return YankApproveOut(
            status="pending",
            needs_second_admin=True,
            primary_admin_id=primary,
            secondary_admin_id=secondary,
        )

    # Wave 7: propagate the finalised yank decision to the source hub so
    # other orchestrators consuming the same /v1/yanks feed pick it up.
    # Non-blocking — propagation failures log + return None; the local
    # catalog already reflects the yank for this orchestrator's runtime
    # gate (services/apps/runtime.py refuses to start yanked instances).
    try:
        await yanks_svc.publish_yank_upstream(
            db, yank_request_id=yank_request_id
        )
    except Exception:
        logger.exception(
            "approve: publish_yank_upstream failed yank=%s; local yank "
            "already authoritative", yank_request_id
        )

    return YankApproveOut(
        status=result.get("status", "approved"),
        needs_second_admin=False,
        primary_admin_id=primary,
        secondary_admin_id=secondary,
    )


@router.post("/{yank_request_id}/reject", response_model=YankRejectOut)
async def reject(
    yank_request_id: UUID,
    body: YankRejectIn | None = None,
    user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> YankRejectOut:
    note = body.note if body is not None else None
    try:
        await yanks_svc.reject_yank(
            db,
            yank_request_id=yank_request_id,
            admin_user_id=user.id,
            note=note,
        )
    except yanks_svc.AlreadyDecidedError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except yanks_svc.YankNotFoundError:
        raise HTTPException(status_code=404, detail="yank not found") from None
    await db.commit()
    return YankRejectOut(status="rejected")


@router.post("/{yank_request_id}/appeal", response_model=YankAppealOut)
async def appeal(
    yank_request_id: UUID,
    body: YankAppealIn,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> YankAppealOut:
    # Creator-owner check: join YankRequest -> AppVersion -> MarketplaceApp.
    row = (
        await db.execute(
            select(YankRequest, MarketplaceApp.creator_user_id)
            .join(AppVersion, AppVersion.id == YankRequest.app_version_id)
            .join(MarketplaceApp, MarketplaceApp.id == AppVersion.app_id)
            .where(YankRequest.id == yank_request_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="yank not found")
    _yank, creator_id = row
    if creator_id != user.id:
        raise HTTPException(status_code=403, detail="only the app creator may appeal")

    try:
        appeal_id = await yanks_svc.file_appeal(
            db,
            yank_request_id=yank_request_id,
            appellant_user_id=user.id,
            reason=body.reason,
        )
    except yanks_svc.YankNotFoundError:
        raise HTTPException(status_code=404, detail="yank not found") from None
    except yanks_svc.YankError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    await db.commit()
    return YankAppealOut(appeal_id=appeal_id)


@router.get("/", response_model=YankListOut)
async def list_yanks(
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    app_version_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> YankListOut:
    stmt = select(YankRequest)
    if status is not None:
        stmt = stmt.where(YankRequest.status == status)
    if severity is not None:
        stmt = stmt.where(YankRequest.severity == severity)
    if app_version_id is not None:
        stmt = stmt.where(YankRequest.app_version_id == app_version_id)

    if not getattr(user, "is_superuser", False):
        # Non-admin: own requests OR yanks against apps they created.
        stmt = (
            stmt.join(AppVersion, AppVersion.id == YankRequest.app_version_id)
            .join(MarketplaceApp, MarketplaceApp.id == AppVersion.app_id)
            .where(
                or_(
                    YankRequest.requester_user_id == user.id,
                    MarketplaceApp.creator_user_id == user.id,
                )
            )
        )

    stmt = stmt.order_by(YankRequest.created_at.desc())
    rows = (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()
    return YankListOut(
        items=[YankOut.model_validate(r) for r in rows],
        limit=limit,
        offset=offset,
        total=len(rows),
    )
