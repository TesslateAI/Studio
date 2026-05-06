"""
Stage 2 — sandbox eval runner for a marketplace submission.

The sandbox runner is the marketplace-side replacement for the orchestrator's
Wave 7 ``services/apps/stage2_sandbox.py``. It runs an adversarial-eval
proxy against a submission's bundle and records a ``adversarial_score``
check. On pass it advances to ``stage3``; on fail it transitions to
``rejected``.

The orchestrator's original implementation pulled an ``AdversarialSuite``
row from its DB. The marketplace doesn't have an adversarial-suite table
of its own — the eval is a deterministic structural-and-content scan on
the submission manifest + declared bundle metadata. This is the same
"deterministic stub for now" pattern the orchestrator used; it produces
real auditable rows so a future plug-in adversarial runner just replaces
:func:`compute_score`.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from . import submissions

__all__ = ["run_stage2_eval", "compute_score", "STAGE2_SCORE_THRESHOLD"]

logger = logging.getLogger(__name__)

STAGE2_SCORE_THRESHOLD: float = 0.5


def compute_score(
    *,
    manifest: dict[str, Any] | None,
    bundle_sha256: str | None,
    bundle_size_bytes: int | None,
) -> float:
    """Deterministic content-aware score in [0, 1].

    The score is built from a handful of cheap signals so the result is
    explainable in the audit trail:

      * +0.30 — manifest is present + a JSON object
      * +0.20 — manifest declares ``required_features`` (any list, even empty)
      * +0.20 — manifest declares ``source_visibility`` and ``forkable``
      * +0.20 — bundle sha256 + size declared (= caller actually uploaded
        a bundle, not a manifest-only submission)
      * +0.10 — manifest carries a ``billing`` block (priced item is more
        likely to have been authored by an accountable creator)
    """
    score = 0.0
    if isinstance(manifest, dict):
        score += 0.30
        if isinstance(manifest.get("required_features"), list):
            score += 0.20
        if (
            manifest.get("source_visibility") not in (None, "")
            and manifest.get("forkable") is not None
        ):
            score += 0.20
        if isinstance(manifest.get("billing"), dict):
            score += 0.10
    if bundle_sha256 and bundle_size_bytes and bundle_size_bytes > 0:
        score += 0.20
    return min(1.0, score)


async def run_stage2_eval(
    db: AsyncSession,
    *,
    submission_id: uuid.UUID,
) -> dict[str, Any]:
    """Run Stage2 sandbox eval; advance stage2 → stage3 on pass else stage2 → rejected.

    Manifest-only / bundle-less submissions short-circuit to a warning
    so the pipeline still walks through to ``stage3``: there's nothing
    to adversarially evaluate, but we don't reject because the upstream
    publisher may complete the bundle out-of-band (a Wave 4 / Wave 7
    flow used by the orchestrator's publisher.py for federated apps).
    """
    sub = await submissions.load_submission(db, submission_id)
    manifest = sub.manifest if isinstance(sub.manifest, dict) else None

    if not manifest and not sub.bundle_sha256:
        await submissions.record_check(
            db,
            submission_id=submission_id,
            stage="stage2",
            name="adversarial_score",
            status="warning",
            message="no manifest or bundle to evaluate; skipping adversarial scan",
            details={"score": None, "skipped": True},
        )
        await submissions.advance_stage(db, submission_id=submission_id, to_stage="stage3")
        logger.info(
            "stage2.eval submission=%s skipped (no manifest or bundle) -> stage3",
            submission_id,
        )
        return {"advanced_to": "stage3", "score": None, "passed": True, "skipped": True}

    score = compute_score(
        manifest=manifest,
        bundle_sha256=sub.bundle_sha256,
        bundle_size_bytes=sub.bundle_size_bytes,
    )
    passed = score >= STAGE2_SCORE_THRESHOLD

    await submissions.record_check(
        db,
        submission_id=submission_id,
        stage="stage2",
        name="adversarial_score",
        status="passed" if passed else "failed",
        message=(
            f"score {score:.2f} >= threshold {STAGE2_SCORE_THRESHOLD:.2f}"
            if passed
            else f"score {score:.2f} < threshold {STAGE2_SCORE_THRESHOLD:.2f}"
        ),
        details={
            "score": str(Decimal(f"{score:.4f}")),
            "threshold": str(Decimal(f"{STAGE2_SCORE_THRESHOLD:.4f}")),
        },
    )

    if passed:
        await submissions.advance_stage(db, submission_id=submission_id, to_stage="stage3")
        target = "stage3"
    else:
        await submissions.advance_stage(
            db,
            submission_id=submission_id,
            to_stage="rejected",
            decision_reason=(
                f"stage2 adversarial score {score:.2f} below threshold "
                f"{STAGE2_SCORE_THRESHOLD:.2f}"
            ),
        )
        target = "rejected"

    logger.info(
        "stage2.eval submission=%s score=%.2f passed=%s -> %s",
        submission_id,
        score,
        passed,
        target,
    )
    return {"advanced_to": target, "score": score, "passed": passed}
