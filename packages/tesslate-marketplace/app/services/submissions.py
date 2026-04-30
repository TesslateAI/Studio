"""
Submission pipeline writers — staged approval lifecycle.

Wave 8: this is the authoritative implementation of the staged approval
pipeline (`stage0` → `stage1` → `stage2` → `stage3` → `approved`/`rejected`).
The orchestrator's `routers/app_submissions.py` becomes a thin proxy that
calls the publish / advance / finalise endpoints exposed on the marketplace
service; those endpoints, in turn, call the helpers below.

Only `stage0` → `stage1` and the terminal transitions are auto-driven by
publish (publish creates a `stage0_received` row and immediately advances
through `stage1` static checks). Stage2 (sandbox) and stage3 (manual review
hand-off) are exposed as explicit advance endpoints so callers (or the
admin UI) can drive them under their own scheduling. The transition table
below is the single source of truth.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Submission, SubmissionCheck

__all__ = [
    "AlreadyTerminalError",
    "CheckStatus",
    "InvalidTransitionError",
    "Stage",
    "STAGE_TO_STATE",
    "SubmissionNotFoundError",
    "SubmissionServiceError",
    "VALID_TRANSITIONS",
    "advance_stage",
    "finalize_submission",
    "list_submissions",
    "load_submission",
    "record_check",
]

logger = logging.getLogger(__name__)

Stage = Literal[
    "stage0",
    "stage1",
    "stage2",
    "stage3",
    "approved",
    "rejected",
    "withdrawn",
]
CheckStatus = Literal["passed", "failed", "warning", "errored", "skipped"]


class SubmissionServiceError(Exception):
    """Base class for submission service errors."""


class SubmissionNotFoundError(SubmissionServiceError):
    """No submission with the given id."""


class InvalidTransitionError(SubmissionServiceError):
    """Attempted stage transition is not in :data:`VALID_TRANSITIONS`."""


class AlreadyTerminalError(SubmissionServiceError):
    """Caller tried to mutate a submission that's already in a terminal state."""


# Valid forward stage transitions. Terminal stages have no outgoing edges; the
# pipeline is strictly forward-only (no retries that go backwards).
VALID_TRANSITIONS: dict[Stage, set[Stage]] = {
    "stage0": {"stage1", "rejected", "withdrawn"},
    "stage1": {"stage2", "rejected", "withdrawn"},
    "stage2": {"stage3", "rejected", "withdrawn"},
    "stage3": {"approved", "rejected", "withdrawn"},
    "approved": set(),
    "rejected": set(),
    "withdrawn": set(),
}


# Map of stage → user-visible state string. Mirrors the state strings the
# orchestrator was using so the federated cache can stay shape-compatible.
STAGE_TO_STATE: dict[Stage, str] = {
    "stage0": "stage0_received",
    "stage1": "stage1_static",
    "stage2": "stage2_dynamic",
    "stage3": "stage3_review",
    "approved": "approved",
    "rejected": "rejected",
    "withdrawn": "withdrawn",
}

_TERMINAL_STAGES: frozenset[Stage] = frozenset({"approved", "rejected", "withdrawn"})


def _assert_valid(from_stage: str, to_stage: str) -> None:
    allowed = VALID_TRANSITIONS.get(from_stage)  # type: ignore[arg-type]
    if allowed is None or to_stage not in allowed:
        raise InvalidTransitionError(
            f"cannot transition {from_stage!r} -> {to_stage!r}"
        )


async def load_submission(db: AsyncSession, submission_id: uuid.UUID | str) -> Submission:
    """Fetch a single submission row, raising :class:`SubmissionNotFoundError`."""
    row = (
        await db.execute(select(Submission).where(Submission.id == submission_id))
    ).scalar_one_or_none()
    if row is None:
        raise SubmissionNotFoundError(str(submission_id))
    return row


async def record_check(
    db: AsyncSession,
    *,
    submission_id: uuid.UUID,
    stage: Stage,
    name: str,
    status: CheckStatus,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> SubmissionCheck:
    """Append a :class:`SubmissionCheck` row for a stage's check.

    The caller owns the surrounding transaction — we just flush so the row
    has a primary key by the time we return.
    """
    check = SubmissionCheck(
        id=uuid.uuid4(),
        submission_id=submission_id,
        stage=stage,
        name=name,
        status=status,
        message=message,
        details=details,
    )
    db.add(check)
    await db.flush()
    return check


async def advance_stage(
    db: AsyncSession,
    *,
    submission_id: uuid.UUID,
    to_stage: Stage,
    decision_reason: str | None = None,
) -> Submission:
    """Transition a submission to the given stage.

    Validates the transition against :data:`VALID_TRANSITIONS`. Terminal
    stages set the matching ``decision`` value. Caller commits.
    """
    sub = await load_submission(db, submission_id)
    if sub.stage in _TERMINAL_STAGES:
        raise AlreadyTerminalError(
            f"submission already {sub.stage!r}"
        )
    _assert_valid(sub.stage, to_stage)

    sub.stage = to_stage
    sub.state = STAGE_TO_STATE[to_stage]
    sub.updated_at = datetime.now(tz=timezone.utc)
    if to_stage in _TERMINAL_STAGES:
        sub.decision = to_stage
        if decision_reason is not None:
            sub.decision_reason = decision_reason
    elif decision_reason is not None:
        # Decision reason is only legitimate on a terminal transition; ignore
        # it elsewhere so callers don't accidentally pollute non-terminal
        # rows with stale decision strings.
        pass

    await db.flush()
    logger.info(
        "submission.advance id=%s -> %s reason=%s",
        submission_id,
        to_stage,
        decision_reason,
    )
    return sub


async def finalize_submission(
    db: AsyncSession,
    *,
    submission_id: uuid.UUID,
    decision: Literal["approved", "rejected", "withdrawn"],
    decision_reason: str | None = None,
) -> Submission:
    """Move a submission to one of the three terminal states.

    This is a convenience wrapper around :func:`advance_stage` that lets the
    caller force a terminal decision from any non-terminal stage. It checks
    :data:`VALID_TRANSITIONS` so the orchestrator can't sneak a force-approve
    from ``stage0`` (rejection from any stage is allowed; approval requires
    the row to be at ``stage3``).
    """
    sub = await load_submission(db, submission_id)
    if sub.stage in _TERMINAL_STAGES:
        raise AlreadyTerminalError(
            f"submission already {sub.stage!r}"
        )
    if decision not in ("approved", "rejected", "withdrawn"):
        raise InvalidTransitionError(
            f"unknown terminal decision {decision!r}"
        )
    if decision == "approved" and sub.stage != "stage3":
        # Approval requires the row to have walked through every stage.
        raise InvalidTransitionError(
            f"cannot approve from stage={sub.stage!r}; must be at 'stage3'"
        )
    return await advance_stage(
        db,
        submission_id=submission_id,
        to_stage=decision,
        decision_reason=decision_reason,
    )


async def list_submissions(
    db: AsyncSession,
    *,
    state: str | None = None,
    stage: str | None = None,
    submitter_handle: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Submission]:
    """Filter helper for the marketplace's admin queue UI."""
    stmt = select(Submission)
    if state is not None:
        stmt = stmt.where(Submission.state == state)
    if stage is not None:
        stmt = stmt.where(Submission.stage == stage)
    if submitter_handle is not None:
        stmt = stmt.where(Submission.submitter_handle == submitter_handle)
    stmt = stmt.order_by(Submission.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)
