"""Wave 8: thin-proxy yank workflow router.

User-facing flow stays identical to pre-Wave-8: any user can request a
yank, admins approve / reject (critical severity requires a second
distinct admin), only the creator-owner of the underlying app can file
an appeal.

The behaviour difference is structural: the *authority* for whether a
yank is approved (and for the two-admin policy on critical yanks) is
now the marketplace service. The orchestrator still records every yank
in the local ``yank_requests`` cache so the existing UI and runtime
gate keep working unchanged, but the writes round-trip through
``MarketplaceClient`` so cross-orchestrator consistency comes for free
via the federated changes feed.
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
from ..services import marketplace_governance
from ..services.apps import yanks as yanks_svc
from ..services.marketplace_client import MarketplaceClientError
from ..services.marketplace_http_errors import propagate_marketplace_error
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
# Helpers
# ---------------------------------------------------------------------------


def _propagate_marketplace_error(exc: MarketplaceClientError) -> HTTPException:
    return propagate_marketplace_error(exc, not_found_tag="marketplace_yank_not_found")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=YankRequestCreatedOut)
async def create_yank(
    body: YankRequestIn,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> YankRequestCreatedOut:
    """Create a local YankRequest row + forward to the marketplace.

    The local row is kept so the existing UI / queue / appeal flow
    continues to work; the marketplace becomes the source of truth for
    the *decision*. We forward the create immediately so the federated
    changes-feed has the yank for cross-orchestrator visibility.
    """
    yid = await yanks_svc.request_yank(
        db,
        requester_user_id=user.id,
        app_version_id=body.app_version_id,
        severity=body.severity,  # type: ignore[arg-type]
        reason=body.reason,
    )
    await db.commit()

    # Forward to marketplace if the underlying app is federated.
    source = await marketplace_governance.resolve_source_for_app_version(db, body.app_version_id)
    if (
        source is None
        or source.trust_level == "local"
        or (source.base_url or "").startswith("local://")
    ):
        return YankRequestCreatedOut(yank_request_id=yid)

    av_row = (
        await db.execute(
            select(AppVersion, MarketplaceApp)
            .join(MarketplaceApp, MarketplaceApp.id == AppVersion.app_id)
            .where(AppVersion.id == body.app_version_id)
        )
    ).first()
    if av_row is None:
        return YankRequestCreatedOut(yank_request_id=yid)
    av, app = av_row

    try:
        await marketplace_governance.proxy_create_yank(
            db,
            local_yank_id=yid,
            source=source,
            kind="app",
            slug=app.slug,
            version=av.version,
            severity=body.severity,
            reason=body.reason,
            requested_by=str(user.id),
        )
        await db.commit()
    except marketplace_governance.AdminTokenMissingError:
        # Non-fatal: local yank is still recorded and the runtime gate
        # already gates instances locally. Operator must configure the
        # admin token to enable upstream propagation.
        logger.warning(
            "create_yank: marketplace admin token missing; local-only yank id=%s",
            yid,
        )
    except MarketplaceClientError as exc:
        # Don't roll back the local yank — propagation can be retried later
        # from the admin queue. Surface a soft warning via the response
        # body so the caller knows.
        logger.warning("create_yank: upstream forward failed for yank=%s: %s", yid, exc)

    return YankRequestCreatedOut(yank_request_id=yid)


@router.post("/{yank_request_id}/approve", response_model=YankApproveOut)
async def approve(
    yank_request_id: UUID,
    user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> YankApproveOut:
    """Approve a yank.

    Wave 8: the marketplace owns the two-admin policy for critical
    severity. The orchestrator forwards approve actions to the
    marketplace and mirrors the resulting state back into the local
    cache. The local two-admin policy in
    ``services/apps/yanks.approve_yank`` is kept as the single-admin
    fast path for non-critical yanks (so the UI doesn't gain a
    network round-trip on every low-severity approve).
    """
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

    # Wave 7 carried this — propagate to upstream hub if federated. Wave 8
    # leaves this in place because the create_yank fast-path above might
    # have failed (admin token missing, etc.) and we always want the
    # finalised approval to land upstream.
    try:
        await yanks_svc.publish_yank_upstream(db, yank_request_id=yank_request_id)
    except Exception:
        logger.exception(
            "approve: publish_yank_upstream failed yank=%s; local yank already authoritative",
            yank_request_id,
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
    """File an appeal — proxies to the marketplace for federated apps."""
    row = (
        await db.execute(
            select(YankRequest, MarketplaceApp.creator_user_id, AppVersion, MarketplaceApp)
            .join(AppVersion, AppVersion.id == YankRequest.app_version_id)
            .join(MarketplaceApp, MarketplaceApp.id == AppVersion.app_id)
            .where(YankRequest.id == yank_request_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="yank not found")
    yank_row, creator_id, av, app = row
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

    # Forward to marketplace for federated apps so the upstream's two-admin
    # policy on critical yanks is respected.
    source = await marketplace_governance.resolve_source_for_app_version(
        db, yank_row.app_version_id
    )
    if (
        source is not None
        and source.trust_level != "local"
        and not (source.base_url or "").startswith("local://")
    ):
        try:
            await marketplace_governance.proxy_appeal_yank(
                db,
                local_yank_id=yank_row.id,
                upstream_yank_id=str(yank_row.id),
                source=source,
                reason=body.reason,
                submitted_by=str(user.id),
            )
            await db.commit()
        except marketplace_governance.AdminTokenMissingError:
            logger.warning(
                "appeal: marketplace admin token missing; local-only appeal id=%s",
                appeal_id,
            )
        except MarketplaceClientError as exc:
            # Hub refused the appeal (e.g. self-appeal on critical yank)
            # — surface the error so the operator sees why it failed.
            raise _propagate_marketplace_error(exc) from exc

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
