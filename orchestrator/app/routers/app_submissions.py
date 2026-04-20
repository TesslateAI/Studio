"""Wave 3: App submissions approval-pipeline router.

Admin-gated endpoints for advancing submissions through stages and
recording per-stage checks. Listing + detail are scoped: admins see all,
creators see only their own submissions.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models import AppSubmission, User
from ..services.apps import stage1_scanner, stage2_sandbox
from ..services.apps import submissions as submissions_svc
from ..users import current_active_user, current_superuser

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
    to_stage: str
    decision_notes: str | None = None


class RecordCheckIn(BaseModel):
    stage: str
    check_name: str
    status: str
    details: dict[str, Any] | None = None


class CheckCreatedOut(BaseModel):
    check_id: UUID


class ScanRunOut(BaseModel):
    """Result of a synchronous scanner run.

    ``submission`` carries the post-scan stage so the UI can refresh without a
    second round-trip. ``result`` is the scanner's own return dict (check
    counts, failure list, score, etc.) — opaque to the router.
    """

    submission: SubmissionDetailOut
    result: dict[str, Any]


# ---------------------------------------------------------------------------
# Endpoints
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
    """Admins see all; non-admin sees only their submissions."""
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


@router.post("/{submission_id}/advance", response_model=SubmissionOut)
async def advance_submission(
    submission_id: UUID,
    body: AdvanceStageIn,
    user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> SubmissionOut:
    try:
        await submissions_svc.advance_stage(
            db,
            submission_id=submission_id,
            to_stage=body.to_stage,  # type: ignore[arg-type]
            reviewer_user_id=user.id,
            decision_notes=body.decision_notes,
        )
    except submissions_svc.SubmissionNotFoundError:
        raise HTTPException(status_code=404, detail="submission not found") from None
    except submissions_svc.InvalidTransitionError as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    # advance_stage only flushes; without an explicit commit the transaction
    # rolls back on session close and the stage change is silently lost.
    await db.commit()

    row = (
        await db.execute(select(AppSubmission).where(AppSubmission.id == submission_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="submission not found")
    return SubmissionOut.model_validate(row)


@router.post("/{submission_id}/checks", response_model=CheckCreatedOut)
async def add_check(
    submission_id: UUID,
    body: RecordCheckIn,
    user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> CheckCreatedOut:
    # Ensure submission exists for a clean 404.
    exists = (
        await db.execute(select(AppSubmission.id).where(AppSubmission.id == submission_id))
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="submission not found")

    check_id = await submissions_svc.record_check(
        db,
        submission_id=submission_id,
        stage=body.stage,  # type: ignore[arg-type]
        check_name=body.check_name,
        status=body.status,  # type: ignore[arg-type]
        details=body.details,
    )
    # record_check only flushes; same persistence pitfall as advance.
    await db.commit()
    return CheckCreatedOut(check_id=check_id)


async def _load_submission_detail(db: AsyncSession, submission_id: UUID) -> SubmissionDetailOut:
    """Re-read a submission + checks after a mutating action, fresh from the DB."""
    row = (
        await db.execute(
            select(AppSubmission)
            .where(AppSubmission.id == submission_id)
            .options(selectinload(AppSubmission.checks))
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="submission not found")
    return SubmissionDetailOut.model_validate(row)


@router.post("/{submission_id}/scan/stage1", response_model=ScanRunOut)
async def run_stage1_scan_endpoint(
    submission_id: UUID,
    _user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> ScanRunOut:
    """Run the Stage1 structural scanner on a submission.

    Preconditions: the submission must currently be at ``stage1``. The
    scanner records per-check rows, then advances stage1 → stage2 on all-pass
    or stage1 → rejected on any hard failure. Use the manual ``/advance``
    endpoint to move stage0 → stage1 first.
    """
    current = (
        await db.execute(select(AppSubmission.stage).where(AppSubmission.id == submission_id))
    ).scalar_one_or_none()
    if current is None:
        raise HTTPException(status_code=404, detail="submission not found")
    if current != "stage1":
        raise HTTPException(
            status_code=409,
            detail=f"submission is at {current!r}; scan requires 'stage1'",
        )

    try:
        result = await stage1_scanner.run_stage1_scan(db, submission_id=submission_id)
    except submissions_svc.SubmissionNotFoundError:
        raise HTTPException(status_code=404, detail="submission not found") from None
    except submissions_svc.InvalidTransitionError as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception:
        await db.rollback()
        raise

    await db.commit()
    detail = await _load_submission_detail(db, submission_id)
    return ScanRunOut(submission=detail, result=result)


@router.post("/{submission_id}/scan/stage2", response_model=ScanRunOut)
async def run_stage2_eval_endpoint(
    submission_id: UUID,
    _user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> ScanRunOut:
    """Run the Stage2 sandbox eval on a submission.

    Preconditions: the submission must currently be at ``stage2``. On pass,
    advances stage2 → stage3. On fail, stage2 → rejected. If no
    ``AdversarialSuite`` is configured the scanner records a warning and
    advances to stage3 so the queue doesn't block.
    """
    current = (
        await db.execute(select(AppSubmission.stage).where(AppSubmission.id == submission_id))
    ).scalar_one_or_none()
    if current is None:
        raise HTTPException(status_code=404, detail="submission not found")
    if current != "stage2":
        raise HTTPException(
            status_code=409,
            detail=f"submission is at {current!r}; eval requires 'stage2'",
        )

    try:
        result = await stage2_sandbox.run_stage2_eval(db, submission_id=submission_id)
    except submissions_svc.SubmissionNotFoundError:
        raise HTTPException(status_code=404, detail="submission not found") from None
    except submissions_svc.InvalidTransitionError as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception:
        await db.rollback()
        raise

    await db.commit()
    detail = await _load_submission_detail(db, submission_id)
    return ScanRunOut(submission=detail, result=result)
