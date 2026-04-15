"""Stage2 ("sandbox eval") runner.

Wave 7 ships the plumbing with a deterministic scoring stub. The final
implementation replaces ``_stub_score`` with a real adversarial run
against the selected ``AdversarialSuite``.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AdversarialSuite, AppSubmission, AppVersion
from . import monitoring, submissions

__all__ = ["run_stage2_eval", "STAGE2_SCORE_THRESHOLD"]

logger = logging.getLogger(__name__)

STAGE2_SCORE_THRESHOLD: float = 0.5
_STUB_SCORE: float = 0.7


def _stub_score(_av: AppVersion) -> float:
    """Deterministic placeholder until the adversarial runner lands."""
    return _STUB_SCORE


async def _latest_suite(db: AsyncSession) -> AdversarialSuite | None:
    return (
        await db.execute(
            select(AdversarialSuite).order_by(AdversarialSuite.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()


async def run_stage2_eval(
    db: AsyncSession,
    *,
    submission_id: UUID,
) -> dict:
    """Run the Stage2 sandbox eval and advance the submission stage."""
    sub = (
        await db.execute(
            select(AppSubmission).where(AppSubmission.id == submission_id)
        )
    ).scalar_one_or_none()
    if sub is None:
        raise submissions.SubmissionNotFoundError(str(submission_id))

    av = (
        await db.execute(
            select(AppVersion).where(AppVersion.id == sub.app_version_id)
        )
    ).scalar_one_or_none()
    if av is None:
        raise LookupError(f"app_version {sub.app_version_id} not found")

    suite = await _latest_suite(db)

    # No suite configured yet: warn and advance so admins can still move the
    # submission forward. The warning is auditable on the submission row.
    if suite is None:
        await submissions.record_check(
            db,
            submission_id=submission_id,
            stage="stage2",
            check_name="no_adversarial_suite",
            status="warning",
            details={"note": "no adversarial suite configured; stage2 skipped"},
        )
        await submissions.advance_stage(
            db, submission_id=submission_id, to_stage="stage3"
        )
        logger.info(
            "stage2.eval submission=%s no_suite -> stage3", submission_id
        )
        return {"advanced_to": "stage3", "suite_id": None, "score": None}

    score = _stub_score(av)
    findings = {"stub": True, "threshold": STAGE2_SCORE_THRESHOLD}
    await monitoring.record_adversarial_run(
        db,
        suite_id=suite.id,
        app_version_id=av.id,
        score=score,
        findings=findings,
    )
    passed = score >= STAGE2_SCORE_THRESHOLD
    await submissions.record_check(
        db,
        submission_id=submission_id,
        stage="stage2",
        check_name="adversarial_score",
        status="passed" if passed else "failed",
        details={
            "score": str(Decimal(str(score))),
            "threshold": str(Decimal(str(STAGE2_SCORE_THRESHOLD))),
            "suite_id": str(suite.id),
        },
    )

    target = "stage3" if passed else "rejected"
    await submissions.advance_stage(
        db,
        submission_id=submission_id,
        to_stage=target,
        decision_notes=(
            None if passed else f"stage2 adversarial score {score} < {STAGE2_SCORE_THRESHOLD}"
        ),
    )
    logger.info(
        "stage2.eval submission=%s suite=%s score=%s -> %s",
        submission_id,
        suite.id,
        score,
        target,
    )
    return {
        "advanced_to": target,
        "suite_id": str(suite.id),
        "score": score,
        "passed": passed,
    }
