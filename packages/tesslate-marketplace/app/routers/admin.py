"""
Admin governance surface — gated behind the ``admin.write`` scope.

Wave 8: when the orchestrator's ``routers/admin_marketplace.py`` invokes a
governance write (force-approve a submission past stage 0/1/2; force-reject
without going through the staged pipeline; override-yank to flip a critical
yank to ``resolved`` without a second-admin appeal), it forwards through
the marketplace's ``MarketplaceClient`` admin endpoints below.

Hosting expectation: Tesslate Official's orchestrator holds a single
static admin token (``MARKETPLACE_ADMIN_TOKEN`` env var) that carries
the ``admin.write`` scope. Self-hosted orchestrators with their own
hub run the equivalent admin token through their own static-token table.

These endpoints DO NOT bypass the changes-feed: every state change still
emits the appropriate ``upsert``/``yank`` op so federated consumers stay
in sync with the override.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_session
from ..models import Submission, YankRequest
from ..schemas import SubmissionOut, YankOut
from ..services import changes_emitter
from ..services import submissions as submissions_svc
from ..services.auth import Principal, get_principal
from ..services.capability_router import requires_capability

router = APIRouter(prefix="/v1/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Pydantic envelopes
# ---------------------------------------------------------------------------


class ForceApproveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_reason: str | None = None
    skip_remaining_stages: bool = True


class ForceRejectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_reason: str


class OverrideYankBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_state: Literal["resolved", "open"]
    resolution: str | None = None
    note: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_submission(row: Submission) -> SubmissionOut:
    from .publish import _serialize  # local import — avoid the router-import cycle

    return _serialize(row)


def _serialize_yank(row: YankRequest) -> YankOut:
    return YankOut(
        id=str(row.id),
        kind=row.kind,
        slug=row.slug,
        version=row.version,
        severity=row.severity,
        reason=row.reason,
        requested_by=row.requested_by,
        state=row.state,
        resolved_at=row.resolved_at,
        resolution=row.resolution,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/submissions/{submission_id}/force-approve",
    response_model=SubmissionOut,
)
@requires_capability("submissions.staged")
async def admin_force_approve(
    submission_id: str,
    body: ForceApproveBody,
    db: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> SubmissionOut:
    """Skip remaining stages and approve a submission.

    Used by superuser admins to push a submission through the queue when
    a manual review stage is blocking shipping. Records the override as
    a stage3 ``admin_override_approve`` check so the audit trail is
    explicit. Always emits the underlying changes-feed op so cache
    consumers learn about the approval.
    """
    principal.require_scope("admin.write")

    row = (
        await db.execute(
            select(Submission)
            .options(selectinload(Submission.checks))
            .where(Submission.id == submission_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "submission_not_found"})
    if row.stage in ("approved", "rejected", "withdrawn"):
        raise HTTPException(
            status_code=409,
            detail={"error": "submission_terminal", "state": row.state},
        )

    # Walk forward to stage3 if the caller asked us to short-circuit; this
    # keeps the audit trail honest (each transition is recorded) while still
    # giving admins the override switch.
    if body.skip_remaining_stages:
        target_path = ("stage1", "stage2", "stage3")
        for next_stage in target_path:
            if row.stage == next_stage:
                continue
            try:
                await submissions_svc.advance_stage(
                    db,
                    submission_id=row.id,
                    to_stage=next_stage,  # type: ignore[arg-type]
                    decision_reason=None,
                )
            except submissions_svc.InvalidTransitionError:
                # Already past this stage; fine.
                continue

    await submissions_svc.record_check(
        db,
        submission_id=row.id,
        stage="stage3",
        name="admin_override_approve",
        status="passed",
        message=body.decision_reason or f"Force-approved by {principal.handle}",
        details={"admin_handle": principal.handle},
    )
    await submissions_svc.finalize_submission(
        db,
        submission_id=row.id,
        decision="approved",
        decision_reason=body.decision_reason or "admin_force_approved",
    )
    await db.commit()

    # Expire the row so the re-query repopulates the relationship — without
    # this, SQLAlchemy's identity map returns the original (empty-checks)
    # object even though we just added rows in this session.
    await db.refresh(row, attribute_names=["checks"])
    return _serialize_submission(row)


@router.post(
    "/submissions/{submission_id}/force-reject",
    response_model=SubmissionOut,
)
@requires_capability("submissions.staged")
async def admin_force_reject(
    submission_id: str,
    body: ForceRejectBody,
    db: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> SubmissionOut:
    """Reject a submission immediately without running remaining stages."""
    principal.require_scope("admin.write")

    row = (
        await db.execute(
            select(Submission)
            .options(selectinload(Submission.checks))
            .where(Submission.id == submission_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "submission_not_found"})
    if row.stage in ("approved", "rejected", "withdrawn"):
        raise HTTPException(
            status_code=409,
            detail={"error": "submission_terminal", "state": row.state},
        )

    await submissions_svc.record_check(
        db,
        submission_id=row.id,
        stage=row.stage,  # type: ignore[arg-type]
        name="admin_override_reject",
        status="failed",
        message=body.decision_reason,
        details={"admin_handle": principal.handle},
    )
    await submissions_svc.finalize_submission(
        db,
        submission_id=row.id,
        decision="rejected",
        decision_reason=body.decision_reason,
    )
    await db.commit()

    # Expire the row so the re-query repopulates the relationship — without
    # this, SQLAlchemy's identity map returns the original (empty-checks)
    # object even though we just added rows in this session.
    await db.refresh(row, attribute_names=["checks"])
    return _serialize_submission(row)


@router.post(
    "/yanks/{yank_id}/override",
    response_model=YankOut,
)
@requires_capability("yanks")
async def admin_override_yank(
    yank_id: str,
    body: OverrideYankBody,
    db: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> YankOut:
    """Force a yank to a particular state without a second-admin appeal.

    Critical yanks normally need a distinct second admin to flip them to
    ``resolved``. This endpoint exists for the case where the second
    admin can't be reached (incident response, hub maintenance) and the
    superuser admin needs to unilaterally close the loop. Emits the
    yank changes-event so federated consumers re-sync.
    """
    principal.require_scope("admin.write")

    row = (
        await db.execute(select(YankRequest).where(YankRequest.id == yank_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "yank_not_found"})

    row.state = body.new_state
    row.resolution = body.resolution or ("admin_override" if body.new_state == "resolved" else None)
    row.resolved_at = datetime.now(timezone.utc) if body.new_state == "resolved" else None
    await db.flush()

    await changes_emitter.emit(
        db,
        op="yank",
        kind=row.kind,
        slug=row.slug,
        version=row.version,
        payload={
            "reason": row.reason,
            "severity": row.severity,
            "yank_id": str(row.id),
            "state": row.state,
            "admin_override": True,
            "admin_handle": principal.handle,
            "note": body.note,
        },
    )
    await db.commit()
    await db.refresh(row)
    return _serialize_yank(row)
