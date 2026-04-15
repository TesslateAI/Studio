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
from ..models import AppSubmission, SubmissionCheck, User
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
    rows = (
        (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()
    )
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
        raise HTTPException(status_code=404, detail="submission not found")
    except submissions_svc.InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))

    row = (
        await db.execute(
            select(AppSubmission).where(AppSubmission.id == submission_id)
        )
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
        await db.execute(
            select(AppSubmission.id).where(AppSubmission.id == submission_id)
        )
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
    return CheckCreatedOut(check_id=check_id)
