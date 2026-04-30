"""Wave 3 + Wave 8: Admin marketplace surface (superuser-gated).

Wave 8 split:
  * Local-only endpoints (queue, yank-queue, monitoring runs, reputation,
    stats) continue to read / write the orchestrator's local cache —
    these are operator dashboards, not governance writes.
  * Force-approve / force-reject / override-yank become thin proxies to
    the marketplace's ``/v1/admin/...`` endpoints (gated behind the
    ``admin.write`` scope). The local cache row is mirrored from the
    marketplace's authoritative response.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, asc, case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import (
    AppSubmission,
    AppVersion,
    MarketplaceApp,
    MonitoringRun,
    SubmissionCheck,
    User,
    YankRequest,
)
from ..services import marketplace_governance
from ..services.apps import monitoring as monitoring_svc
from ..services.marketplace_client import (
    MarketplaceAuthError,
    MarketplaceClientError,
    MarketplaceNotFoundError,
    MarketplaceServerError,
    UnsupportedCapabilityError,
)
from ..users import current_superuser

logger = logging.getLogger(__name__)

router = APIRouter()
IN_FLIGHT_STAGES = ("stage0", "stage1", "stage2", "stage3")


def _propagate_marketplace_error(exc: MarketplaceClientError) -> HTTPException:
    if isinstance(exc, MarketplaceAuthError):
        return HTTPException(status_code=502, detail={
            "error": "marketplace_auth_failed", "details": str(exc),
        })
    if isinstance(exc, MarketplaceNotFoundError):
        return HTTPException(status_code=404, detail={
            "error": "marketplace_not_found", "details": str(exc),
        })
    if isinstance(exc, UnsupportedCapabilityError):
        return HTTPException(status_code=501, detail={
            "error": "marketplace_unsupported_capability", "capability": exc.capability,
        })
    if isinstance(exc, MarketplaceServerError):
        return HTTPException(status_code=502, detail={
            "error": "marketplace_unavailable", "details": str(exc),
        })
    return HTTPException(status_code=502, detail={
        "error": "marketplace_error", "details": str(exc),
    })


class QueueItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    submission_id: UUID
    app_version_id: UUID
    app_id: UUID
    app_name: str | None = None
    version: str | None = None
    stage: str
    sla_deadline_at: datetime | None = None
    stage_entered_at: datetime | None = None
    check_count: int = 0


class QueueListOut(BaseModel):
    items: list[QueueItemOut]
    limit: int
    offset: int


class YankQueueItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    app_version_id: UUID
    severity: str
    status: str
    reason: str
    created_at: datetime | None = None


class YankQueueOut(BaseModel):
    items: list[YankQueueItemOut]
    limit: int
    offset: int


class MonitoringStartIn(BaseModel):
    app_version_id: UUID
    kind: str


class RunCreatedOut(BaseModel):
    run_id: UUID


class MonitoringFinishIn(BaseModel):
    status: str
    findings: dict[str, Any] | None = None


class AdversarialRunIn(BaseModel):
    suite_id: UUID
    app_version_id: UUID
    score: float | None = None
    findings: dict[str, Any] | None = None


class ReputationDeltaIn(BaseModel):
    delta_score: float | None = None
    delta_approvals: int = 0
    delta_yanks: int = 0
    delta_critical_yanks: int = 0


class StatsOut(BaseModel):
    apps_total: int
    apps_approved: int
    apps_pending: int
    yanks_pending: int
    submissions_in_flight: int
    monitoring_runs_24h: int


@router.get("/queue", response_model=QueueListOut)
async def admin_queue(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> QueueListOut:
    cc = (
        select(
            SubmissionCheck.submission_id.label("sid"), func.count(SubmissionCheck.id).label("cnt")
        )
        .group_by(SubmissionCheck.submission_id)
        .subquery()
    )
    stmt = (
        select(
            AppSubmission.id,
            AppSubmission.app_version_id,
            AppSubmission.stage,
            AppSubmission.sla_deadline_at,
            AppSubmission.stage_entered_at,
            AppVersion.app_id,
            AppVersion.version,
            MarketplaceApp.name,
            func.coalesce(cc.c.cnt, 0),
        )
        .join(AppVersion, AppVersion.id == AppSubmission.app_version_id)
        .join(MarketplaceApp, MarketplaceApp.id == AppVersion.app_id)
        .outerjoin(cc, cc.c.sid == AppSubmission.id)
        .where(AppSubmission.stage.in_(IN_FLIGHT_STAGES))
        .order_by(asc(AppSubmission.sla_deadline_at.is_(None)), asc(AppSubmission.sla_deadline_at))
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).all()
    items = [
        QueueItemOut(
            submission_id=r[0],
            app_version_id=r[1],
            stage=r[2],
            sla_deadline_at=r[3],
            stage_entered_at=r[4],
            app_id=r[5],
            version=r[6],
            app_name=r[7],
            check_count=int(r[8] or 0),
        )
        for r in rows
    ]
    return QueueListOut(items=items, limit=limit, offset=offset)


@router.get("/yank-queue", response_model=YankQueueOut)
async def yank_queue(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> YankQueueOut:
    severity_rank = case(
        (YankRequest.severity == "critical", 3),
        (YankRequest.severity == "medium", 2),
        (YankRequest.severity == "low", 1),
        else_=0,
    )
    stmt = (
        select(YankRequest)
        .where(YankRequest.status == "pending")
        .order_by(desc(severity_rank), asc(YankRequest.created_at))
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return YankQueueOut(
        items=[YankQueueItemOut.model_validate(r) for r in rows],
        limit=limit,
        offset=offset,
    )


@router.post("/monitoring/runs", response_model=RunCreatedOut)
async def start_monitoring(
    body: MonitoringStartIn,
    _user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> RunCreatedOut:
    run_id = await monitoring_svc.start_monitoring_run(
        db,
        app_version_id=body.app_version_id,
        kind=body.kind,  # type: ignore[arg-type]
    )
    return RunCreatedOut(run_id=run_id)


@router.patch("/monitoring/runs/{run_id}", status_code=204)
async def finish_monitoring(
    run_id: UUID,
    body: MonitoringFinishIn,
    _user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        await monitoring_svc.finish_monitoring_run(
            db,
            run_id=run_id,
            status=body.status,
            findings=body.findings,  # type: ignore[arg-type]
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="monitoring run not found") from None
    return Response(status_code=204)


@router.post("/adversarial/runs", response_model=RunCreatedOut)
async def adversarial_run(
    body: AdversarialRunIn,
    _user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> RunCreatedOut:
    run_id = await monitoring_svc.record_adversarial_run(
        db,
        suite_id=body.suite_id,
        app_version_id=body.app_version_id,
        score=body.score,
        findings=body.findings,
    )
    return RunCreatedOut(run_id=run_id)


@router.post("/reputation/{user_id}", status_code=204)
async def reputation_upsert(
    user_id: UUID,
    body: ReputationDeltaIn,
    _user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await monitoring_svc.upsert_creator_reputation(
        db,
        user_id=user_id,
        delta_score=Decimal(str(body.delta_score))
        if body.delta_score is not None
        else Decimal("0"),
        delta_approvals=body.delta_approvals,
        delta_yanks=body.delta_yanks,
        delta_critical_yanks=body.delta_critical_yanks,
    )
    return Response(status_code=204)


@router.get("/stats", response_model=StatsOut)
async def stats(
    _user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> StatsOut:
    now = datetime.now(tz=UTC)
    cutoff = now - timedelta(hours=24)

    async def _count(stmt):
        return (await db.execute(stmt)).scalar_one()

    apps_total = await _count(select(func.count(MarketplaceApp.id)))
    apps_approved = await _count(
        select(func.count(MarketplaceApp.id)).where(MarketplaceApp.state == "approved")
    )
    apps_pending = await _count(
        select(func.count(MarketplaceApp.id)).where(
            MarketplaceApp.state.in_(("pending_stage1", "pending_stage2", "draft"))
        )
    )
    yanks_pending = await _count(
        select(func.count(YankRequest.id)).where(YankRequest.status == "pending")
    )
    submissions_in_flight = await _count(
        select(func.count(AppSubmission.id)).where(AppSubmission.stage.in_(IN_FLIGHT_STAGES))
    )
    monitoring_runs_24h = await _count(
        select(func.count(MonitoringRun.id)).where(and_(MonitoringRun.created_at >= cutoff))
    )
    return StatsOut(
        apps_total=int(apps_total or 0),
        apps_approved=int(apps_approved or 0),
        apps_pending=int(apps_pending or 0),
        yanks_pending=int(yanks_pending or 0),
        submissions_in_flight=int(submissions_in_flight or 0),
        monitoring_runs_24h=int(monitoring_runs_24h or 0),
    )


# ---------------------------------------------------------------------------
# Wave 8: governance overrides — proxied to the marketplace under admin.write
# ---------------------------------------------------------------------------


class ForceDecisionIn(BaseModel):
    decision_reason: str | None = None


class ForceRejectIn(BaseModel):
    decision_reason: str


class OverrideYankIn(BaseModel):
    new_state: str  # resolved | open
    resolution: str | None = None
    note: str | None = None


@router.post("/submissions/{submission_id}/force-approve")
async def force_approve(
    submission_id: UUID,
    body: ForceDecisionIn | None = None,
    user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    sub = (
        await db.execute(select(AppSubmission).where(AppSubmission.id == submission_id))
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="submission not found")
    source = await marketplace_governance.resolve_source_for_app_version(
        db, sub.app_version_id
    )
    if source is None:
        raise HTTPException(status_code=409, detail="no marketplace source")

    decision_reason = (body.decision_reason if body else None) or f"force_approved_by_{user.id}"
    try:
        envelope = await marketplace_governance.proxy_admin_force_approve(
            db,
            local_submission_id=sub.id,
            upstream_submission_id=str(sub.id),
            source=source,
            decision_reason=decision_reason,
        )
    except marketplace_governance.AdminTokenMissingError as exc:
        raise HTTPException(status_code=503, detail={
            "error": "marketplace_admin_token_missing", "message": str(exc),
        }) from exc
    except MarketplaceClientError as exc:
        raise _propagate_marketplace_error(exc) from exc

    sub.reviewer_user_id = user.id
    await db.commit()
    return {"submission": envelope}


@router.post("/submissions/{submission_id}/force-reject")
async def force_reject(
    submission_id: UUID,
    body: ForceRejectIn,
    user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    sub = (
        await db.execute(select(AppSubmission).where(AppSubmission.id == submission_id))
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="submission not found")
    source = await marketplace_governance.resolve_source_for_app_version(
        db, sub.app_version_id
    )
    if source is None:
        raise HTTPException(status_code=409, detail="no marketplace source")

    try:
        envelope = await marketplace_governance.proxy_admin_force_reject(
            db,
            local_submission_id=sub.id,
            upstream_submission_id=str(sub.id),
            source=source,
            decision_reason=body.decision_reason,
        )
    except marketplace_governance.AdminTokenMissingError as exc:
        raise HTTPException(status_code=503, detail={
            "error": "marketplace_admin_token_missing", "message": str(exc),
        }) from exc
    except MarketplaceClientError as exc:
        raise _propagate_marketplace_error(exc) from exc

    sub.reviewer_user_id = user.id
    await db.commit()
    return {"submission": envelope}


@router.post("/yanks/{yank_request_id}/override")
async def override_yank(
    yank_request_id: UUID,
    body: OverrideYankIn,
    user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    yank = (
        await db.execute(select(YankRequest).where(YankRequest.id == yank_request_id))
    ).scalar_one_or_none()
    if yank is None:
        raise HTTPException(status_code=404, detail="yank not found")
    source = await marketplace_governance.resolve_source_for_app_version(
        db, yank.app_version_id
    )
    if source is None:
        raise HTTPException(status_code=409, detail="no marketplace source")
    if body.new_state not in ("resolved", "open"):
        raise HTTPException(status_code=400, detail="invalid new_state")

    token = marketplace_governance.select_token_for_write(source)
    client = marketplace_governance.default_client_factory(source, token)
    try:
        envelope = await client.admin_override_yank(
            str(yank.id),
            new_state=body.new_state,
            resolution=body.resolution,
            note=body.note or f"override_by_{user.id}",
        )
    except marketplace_governance.AdminTokenMissingError as exc:
        raise HTTPException(status_code=503, detail={
            "error": "marketplace_admin_token_missing", "message": str(exc),
        }) from exc
    except MarketplaceClientError as exc:
        raise _propagate_marketplace_error(exc) from exc
    finally:
        await marketplace_governance._safe_close(client)  # noqa: SLF001

    await marketplace_governance.mirror_yank_into_cache(
        db, local_yank_id=yank.id, marketplace_envelope=envelope
    )
    await db.commit()
    return {"yank": envelope}
