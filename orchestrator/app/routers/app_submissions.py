"""Wave 8: thin-proxy app submissions router.

Reads continue to serve the local cache (so the existing UI doesn't need
to change). Mutating endpoints forward to the federated marketplace
service via :mod:`services.marketplace_governance` and mirror the
marketplace's authoritative state into the local cache row.

Stage advancement and finalisation rules are now enforced server-side
on the marketplace; the orchestrator just relays the admin's request.
The marketplace returns the standardized ``submissions.staged`` envelope
which we mirror into ``app_submissions`` + ``submission_checks`` so
existing readers (admin queue, app detail page) keep rendering
identically.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models import AppSubmission, AppVersion, MarketplaceApp, MarketplaceSource, User
from ..services import marketplace_governance
from ..services.marketplace_client import (
    MarketplaceAuthError,
    MarketplaceClientError,
    MarketplaceNotFoundError,
    MarketplaceServerError,
    UnsupportedCapabilityError,
)
from ..users import current_active_user, current_superuser

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models (inline)
# ---------------------------------------------------------------------------


class SubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    app_version_id: UUID
    submitter_user_id: UUID | None = None
    stage: str
    decision: str
    reviewer_user_id: UUID | None = None
    decision_notes: str | None = None


class CheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    submission_id: UUID
    stage: str
    check_name: str
    status: str
    details: dict[str, Any] = Field(default_factory=dict)


class SubmissionDetailOut(SubmissionOut):
    checks: list[CheckOut] = Field(default_factory=list)


class SubmissionListOut(BaseModel):
    items: list[SubmissionOut]
    limit: int
    offset: int
    total: int


class AdvanceStageIn(BaseModel):
    """Wave 8 input — `to_stage` is now optional.

    The marketplace decides which stage to advance to next based on the
    submission's current stage, so callers don't need to specify a target.
    Kept around for backwards-compat with existing UI calls; if the value
    differs from the marketplace's chosen stage the marketplace's
    decision wins.
    """

    to_stage: str | None = None
    decision_notes: str | None = None


class FinalizeIn(BaseModel):
    decision: str  # approved | rejected | withdrawn
    decision_reason: str | None = None


class CheckCreatedOut(BaseModel):
    check_id: UUID


class ScanRunOut(BaseModel):
    submission: SubmissionDetailOut
    result: dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_source_for_submission(
    db: AsyncSession, submission_id: UUID
) -> tuple[AppSubmission, MarketplaceSource | None]:
    """Resolve the cache row + marketplace source backing a submission."""
    sub = (
        await db.execute(
            select(AppSubmission).where(AppSubmission.id == submission_id)
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="submission not found")
    source = await marketplace_governance.resolve_source_for_app_version(
        db, sub.app_version_id
    )
    return sub, source


def _upstream_id_for(sub: AppSubmission) -> str:
    """Map the local submission row to the upstream marketplace id.

    Pre-Wave-8 submissions used the same UUID on both sides (the local
    insert mirrored the marketplace's create response). Wave 8 keeps
    the same convention — the row's id IS the upstream id when the
    marketplace creates it. For legacy rows that pre-date the proxy we
    still pass the local id; the marketplace will return 404, which
    surfaces clearly to the operator.
    """
    return str(sub.id)


def _propagate_marketplace_error(exc: MarketplaceClientError) -> HTTPException:
    """Translate a typed MarketplaceClientError into a clean HTTPException."""
    if isinstance(exc, MarketplaceAuthError):
        return HTTPException(status_code=502, detail={
            "error": "marketplace_auth_failed",
            "details": str(exc),
        })
    if isinstance(exc, MarketplaceNotFoundError):
        # Cache and upstream out of sync — surface 404 so admin sees it.
        return HTTPException(status_code=404, detail={
            "error": "marketplace_submission_not_found",
            "details": str(exc),
        })
    if isinstance(exc, UnsupportedCapabilityError):
        return HTTPException(status_code=501, detail={
            "error": "marketplace_unsupported_capability",
            "capability": exc.capability,
        })
    if isinstance(exc, MarketplaceServerError):
        return HTTPException(status_code=502, detail={
            "error": "marketplace_unavailable",
            "details": str(exc),
        })
    return HTTPException(status_code=502, detail={
        "error": "marketplace_error",
        "details": str(exc),
    })


# ---------------------------------------------------------------------------
# Read endpoints — local cache fall-through (mirror is kept fresh by the
# changes-feed sync worker + the proxy mirror calls below).
# ---------------------------------------------------------------------------


@router.get("/", response_model=SubmissionListOut)
async def list_submissions(
    stage: str | None = Query(default=None),
    reviewer_user_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> SubmissionListOut:
    """Admins see all; non-admin sees only their submissions. Local-cache read."""
    stmt = select(AppSubmission)
    if stage is not None:
        stmt = stmt.where(AppSubmission.stage == stage)
    if reviewer_user_id is not None:
        stmt = stmt.where(AppSubmission.reviewer_user_id == reviewer_user_id)
    if not getattr(user, "is_superuser", False):
        stmt = stmt.where(AppSubmission.submitter_user_id == user.id)
    stmt = stmt.order_by(AppSubmission.stage_entered_at.desc())
    rows = (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()
    return SubmissionListOut(
        items=[SubmissionOut.model_validate(r) for r in rows],
        limit=limit,
        offset=offset,
        total=len(rows),
    )


@router.get("/{submission_id}", response_model=SubmissionDetailOut)
async def get_submission(
    submission_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> SubmissionDetailOut:
    stmt = (
        select(AppSubmission)
        .where(AppSubmission.id == submission_id)
        .options(selectinload(AppSubmission.checks))
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="submission not found")
    if not getattr(user, "is_superuser", False) and row.submitter_user_id != user.id:
        raise HTTPException(status_code=403, detail="not authorized")
    return SubmissionDetailOut(
        id=row.id,
        app_version_id=row.app_version_id,
        submitter_user_id=row.submitter_user_id,
        stage=row.stage,
        decision=row.decision,
        reviewer_user_id=row.reviewer_user_id,
        decision_notes=row.decision_notes,
        checks=[CheckOut.model_validate(c) for c in (row.checks or [])],
    )


# ---------------------------------------------------------------------------
# Write endpoints — proxy to marketplace, mirror state into cache
# ---------------------------------------------------------------------------


async def _load_detail_after_mutation(
    db: AsyncSession, submission_id: UUID
) -> SubmissionDetailOut:
    row = (
        await db.execute(
            select(AppSubmission)
            .where(AppSubmission.id == submission_id)
            .options(selectinload(AppSubmission.checks))
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="submission not found")
    return SubmissionDetailOut(
        id=row.id,
        app_version_id=row.app_version_id,
        submitter_user_id=row.submitter_user_id,
        stage=row.stage,
        decision=row.decision,
        reviewer_user_id=row.reviewer_user_id,
        decision_notes=row.decision_notes,
        checks=[CheckOut.model_validate(c) for c in (row.checks or [])],
    )


@router.post("/{submission_id}/advance", response_model=SubmissionOut)
async def advance_submission(
    submission_id: UUID,
    body: AdvanceStageIn,
    user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> SubmissionOut:
    """Forward the advance to the marketplace; mirror the response.

    Wave 8: the marketplace decides what stage to run next based on the
    submission's current stage. The optional ``to_stage`` body parameter
    is ignored when the marketplace owns the row — the marketplace's
    advance endpoint encapsulates the stage logic.
    """
    sub, source = await _resolve_source_for_submission(db, submission_id)
    if source is None:
        raise HTTPException(
            status_code=409,
            detail="submission has no marketplace source — cannot advance",
        )

    try:
        await marketplace_governance.proxy_advance_submission(
            db,
            local_submission_id=sub.id,
            upstream_submission_id=_upstream_id_for(sub),
            source=source,
        )
    except marketplace_governance.AdminTokenMissingError as exc:
        raise HTTPException(status_code=503, detail={
            "error": "marketplace_admin_token_missing",
            "message": str(exc),
        }) from exc
    except MarketplaceClientError as exc:
        raise _propagate_marketplace_error(exc) from exc

    # Mirror reviewer for local audit trail.
    sub.reviewer_user_id = user.id
    if body.decision_notes is not None:
        sub.decision_notes = body.decision_notes
    await db.commit()

    refreshed = (
        await db.execute(select(AppSubmission).where(AppSubmission.id == submission_id))
    ).scalar_one()
    return SubmissionOut.model_validate(refreshed)


@router.post("/{submission_id}/finalize", response_model=SubmissionOut)
async def finalize_submission(
    submission_id: UUID,
    body: FinalizeIn,
    user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> SubmissionOut:
    """Forward the terminal decision to the marketplace; mirror the response."""
    sub, source = await _resolve_source_for_submission(db, submission_id)
    if source is None:
        raise HTTPException(
            status_code=409,
            detail="submission has no marketplace source — cannot finalise",
        )
    if body.decision not in ("approved", "rejected", "withdrawn"):
        raise HTTPException(status_code=400, detail="invalid decision")

    try:
        await marketplace_governance.proxy_finalize_submission(
            db,
            local_submission_id=sub.id,
            upstream_submission_id=_upstream_id_for(sub),
            source=source,
            decision=body.decision,
            decision_reason=body.decision_reason,
        )
    except marketplace_governance.AdminTokenMissingError as exc:
        raise HTTPException(status_code=503, detail={
            "error": "marketplace_admin_token_missing",
            "message": str(exc),
        }) from exc
    except MarketplaceClientError as exc:
        raise _propagate_marketplace_error(exc) from exc

    sub.reviewer_user_id = user.id
    await db.commit()
    refreshed = (
        await db.execute(select(AppSubmission).where(AppSubmission.id == submission_id))
    ).scalar_one()
    return SubmissionOut.model_validate(refreshed)


# Backwards-compat scan endpoints — both call ``advance`` so existing
# admin-UI buttons keep working. The marketplace decides which scanner
# to run based on the row's stage.


@router.post("/{submission_id}/scan/stage1", response_model=ScanRunOut)
async def run_stage1_scan_endpoint(
    submission_id: UUID,
    user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> ScanRunOut:
    sub, source = await _resolve_source_for_submission(db, submission_id)
    if source is None:
        raise HTTPException(status_code=409, detail="no marketplace source")
    if sub.stage != "stage1":
        raise HTTPException(
            status_code=409,
            detail=f"submission is at {sub.stage!r}; scan requires 'stage1'",
        )

    try:
        envelope = await marketplace_governance.proxy_advance_submission(
            db,
            local_submission_id=sub.id,
            upstream_submission_id=_upstream_id_for(sub),
            source=source,
        )
    except marketplace_governance.AdminTokenMissingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except MarketplaceClientError as exc:
        raise _propagate_marketplace_error(exc) from exc
    sub.reviewer_user_id = user.id
    await db.commit()
    detail = await _load_detail_after_mutation(db, submission_id)
    return ScanRunOut(submission=detail, result={
        "advanced_to": envelope.get("stage"),
        "checks": envelope.get("checks", []),
    })


@router.post("/{submission_id}/scan/stage2", response_model=ScanRunOut)
async def run_stage2_eval_endpoint(
    submission_id: UUID,
    user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> ScanRunOut:
    sub, source = await _resolve_source_for_submission(db, submission_id)
    if source is None:
        raise HTTPException(status_code=409, detail="no marketplace source")
    if sub.stage != "stage2":
        raise HTTPException(
            status_code=409,
            detail=f"submission is at {sub.stage!r}; eval requires 'stage2'",
        )

    try:
        envelope = await marketplace_governance.proxy_advance_submission(
            db,
            local_submission_id=sub.id,
            upstream_submission_id=_upstream_id_for(sub),
            source=source,
        )
    except marketplace_governance.AdminTokenMissingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except MarketplaceClientError as exc:
        raise _propagate_marketplace_error(exc) from exc
    sub.reviewer_user_id = user.id
    await db.commit()
    detail = await _load_detail_after_mutation(db, submission_id)
    return ScanRunOut(submission=detail, result={
        "advanced_to": envelope.get("stage"),
        "checks": envelope.get("checks", []),
    })
