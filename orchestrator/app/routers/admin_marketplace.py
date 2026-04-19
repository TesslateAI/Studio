"""Wave 3: Admin marketplace surface (superuser-gated)."""

from __future__ import annotations

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
from ..services.apps import monitoring as monitoring_svc
from ..users import current_superuser

router = APIRouter()
IN_FLIGHT_STAGES = ("stage0", "stage1", "stage2", "stage3")


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
