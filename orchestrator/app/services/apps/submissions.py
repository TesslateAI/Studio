"""App submissions service — staged approval pipeline for AppVersions.

Stages advance strictly through VALID_TRANSITIONS. Terminal states
('approved', 'rejected') cascade to the underlying AppVersion's
approval_state as a wave-2 shortcut — we don't yet distinguish stage1 vs
stage2 on AV, so approved maps to 'stage2_approved'.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AppSubmission, AppVersion, SubmissionCheck

__all__ = [
    "Stage",
    "CheckStatus",
    "SubmissionError",
    "InvalidTransitionError",
    "SubmissionNotFoundError",
    "VALID_TRANSITIONS",
    "advance_stage",
    "record_check",
    "list_submissions",
]

logger = logging.getLogger(__name__)

Stage = Literal["stage0", "stage1", "stage2", "stage3", "approved", "rejected"]
CheckStatus = Literal["passed", "failed", "warning", "errored"]


class SubmissionError(Exception):
    """Base class for submission service errors."""


class InvalidTransitionError(SubmissionError):
    """Attempted stage transition is not in VALID_TRANSITIONS."""


class SubmissionNotFoundError(SubmissionError):
    """No submission with the given id."""


VALID_TRANSITIONS: dict[Stage, set[Stage]] = {
    "stage0": {"stage1", "rejected"},
    "stage1": {"stage2", "rejected"},
    "stage2": {"stage3", "rejected"},
    "stage3": {"approved", "rejected"},
    "approved": set(),
    "rejected": set(),
}


def _assert_valid(from_stage: str, to_stage: str) -> None:
    allowed = VALID_TRANSITIONS.get(from_stage)  # type: ignore[arg-type]
    if allowed is None or to_stage not in allowed:
        raise InvalidTransitionError(
            f"cannot transition {from_stage!r} -> {to_stage!r}"
        )


async def advance_stage(
    db: AsyncSession,
    *,
    submission_id: UUID,
    to_stage: Stage,
    reviewer_user_id: UUID | None = None,
    decision_notes: str | None = None,
) -> None:
    """Transition a submission. Validates against VALID_TRANSITIONS.

    On terminal stages, cascades the decision to the underlying
    AppVersion.approval_state.
    """
    row = (
        await db.execute(
            select(AppSubmission)
            .where(AppSubmission.id == submission_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise SubmissionNotFoundError(str(submission_id))

    _assert_valid(row.stage, to_stage)

    now = datetime.now(tz=timezone.utc)
    row.stage = to_stage
    row.stage_entered_at = now
    if reviewer_user_id is not None:
        row.reviewer_user_id = reviewer_user_id
    if decision_notes is not None:
        row.decision_notes = decision_notes
    if to_stage in ("approved", "rejected"):
        row.decision = to_stage

    if to_stage in ("approved", "rejected"):
        av = (
            await db.execute(
                select(AppVersion)
                .where(AppVersion.id == row.app_version_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if av is not None:
            av.approval_state = (
                "stage2_approved" if to_stage == "approved" else "rejected"
            )

    await db.flush()
    logger.info(
        "submission.advance id=%s -> %s reviewer=%s",
        submission_id,
        to_stage,
        reviewer_user_id,
    )


async def record_check(
    db: AsyncSession,
    *,
    submission_id: UUID,
    stage: Stage,
    check_name: str,
    status: CheckStatus,
    details: dict | None = None,
) -> UUID:
    """Append a SubmissionCheck row."""
    check_id = uuid.uuid4()
    db.add(
        SubmissionCheck(
            id=check_id,
            submission_id=submission_id,
            stage=stage,
            check_name=check_name,
            status=status,
            details=details or {},
        )
    )
    await db.flush()
    return check_id


async def list_submissions(
    db: AsyncSession,
    *,
    stage: Stage | None = None,
    reviewer_user_id: UUID | None = None,
    limit: int = 50,
) -> list[dict]:
    """Filter helper for admin queue UI."""
    stmt = select(AppSubmission)
    if stage is not None:
        stmt = stmt.where(AppSubmission.stage == stage)
    if reviewer_user_id is not None:
        stmt = stmt.where(AppSubmission.reviewer_user_id == reviewer_user_id)
    stmt = stmt.order_by(AppSubmission.stage_entered_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "app_version_id": r.app_version_id,
            "submitter_user_id": r.submitter_user_id,
            "stage": r.stage,
            "decision": r.decision,
            "reviewer_user_id": r.reviewer_user_id,
            "decision_notes": r.decision_notes,
            "stage_entered_at": r.stage_entered_at,
        }
        for r in rows
    ]
