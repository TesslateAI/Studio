"""Periodic canary / drift monitoring sweep for an approved AppVersion.

Re-runs the adversarial suite stub against an already-approved version.
If the run fails, we open a ``medium`` yank request on behalf of the
configured platform admin. If no admin is configured we log and return —
better to surface the failure in logs than to drop the signal silently.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from . import monitoring, yanks

__all__ = ["run_monitoring_sweep", "MONITORING_SCORE_THRESHOLD"]

logger = logging.getLogger(__name__)

MONITORING_SCORE_THRESHOLD: float = 0.7
_STUB_SCORE: float = 0.68


def _stub_score() -> float:
    """Deterministic placeholder until the adversarial runner lands."""
    return _STUB_SCORE


def _platform_admin_id() -> UUID | None:
    from ...config import get_settings

    raw = (get_settings().platform_admin_user_id or "").strip()
    if not raw:
        return None
    try:
        return UUID(raw)
    except (ValueError, TypeError):
        logger.warning("monitoring: invalid platform_admin_user_id=%r", raw)
        return None


async def run_monitoring_sweep(
    db: AsyncSession,
    *,
    app_version_id: UUID,
) -> dict:
    """Run one monitoring sweep; auto-open a yank on failure when possible."""
    run_id = await monitoring.start_monitoring_run(
        db, app_version_id=app_version_id, kind="canary"
    )
    score = _stub_score()
    passed = score >= MONITORING_SCORE_THRESHOLD
    findings = {
        "stub": True,
        "score": str(Decimal(str(score))),
        "threshold": str(Decimal(str(MONITORING_SCORE_THRESHOLD))),
    }
    await monitoring.finish_monitoring_run(
        db,
        run_id=run_id,
        status="passed" if passed else "failed",
        findings=findings,
    )

    result: dict = {
        "run_id": str(run_id),
        "score": score,
        "passed": passed,
        "yank_requested": False,
    }
    if passed:
        logger.info(
            "monitoring.sweep av=%s run=%s score=%s passed",
            app_version_id,
            run_id,
            score,
        )
        return result

    admin_id = _platform_admin_id()
    if admin_id is None:
        logger.warning(
            "monitoring: failed but no auto-yank admin configured av=%s run=%s score=%s",
            app_version_id,
            run_id,
            score,
        )
        result["yank_skipped_reason"] = "no_platform_admin_configured"
        return result

    yank_id = await yanks.request_yank(
        db,
        requester_user_id=admin_id,
        app_version_id=app_version_id,
        severity="medium",
        reason=(
            f"auto: monitoring canary score {score} < {MONITORING_SCORE_THRESHOLD}"
        ),
    )
    result["yank_requested"] = True
    result["yank_request_id"] = str(yank_id)
    logger.info(
        "monitoring.sweep av=%s run=%s score=%s failed -> yank=%s",
        app_version_id,
        run_id,
        score,
        yank_id,
    )
    return result
