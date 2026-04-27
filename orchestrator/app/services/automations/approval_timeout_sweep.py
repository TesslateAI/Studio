"""Approval-timeout sweep (Phase 4).

The dispatcher writes ``automation_approval_requests.expires_at``
when it pauses a run on a contract breach (see
``dispatcher._handle_contract_breach``), but no writer ever flips the
row to "timed out". Without this sweep an unanswered approval request
holds its parent run in ``waiting_approval`` forever and the worker
never gets unblocked.

Algorithm
---------
Per call:

1. SELECT requests ``WHERE expires_at < now() AND resolved_at IS
   NULL``.
2. For each, in one transaction:

   * UPDATE the request: ``resolved_at=now()``,
     ``response={"choice": "expired", "notes": "approval_timeout"}``.
   * UPDATE the parent ``automation_runs`` row: ``status='failed'``,
     ``ended_at=now()``, ``paused_reason='approval_timeout'``.

The parent run is intentionally driven straight to ``failed`` (not
``expired``) — an unanswered approval is a terminal user decision in
the same way an explicit "deny" would be, so ``failed`` keeps the
status taxonomy consistent with the existing approval-deny path.

Lease fencing
-------------
A leader-side sweep that flips status MUST verify the lease on every
batch — see :func:`_verify_lease_or_raise`. Without this, a deposed
leader could mark approvals timed-out under a stale term while the
new leader is also doing the same work, racing on the same rows.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .intents import LeaseLost

logger = logging.getLogger(__name__)


_BATCH_LIMIT = 500


async def sweep_expired_approvals(
    db: AsyncSession,
    *,
    current_term: int,
) -> int:
    """Mark expired approval requests timed-out and fail their runs.

    Parameters
    ----------
    db:
        Session used for both the SELECT and the per-row UPDATEs. The
        caller commits at the end of the sweep.
    current_term:
        The leader term that initiated the sweep. Verified against the
        live ``controller_leases`` row before each row mutation; a
        mismatch raises :class:`LeaseLost` so the supervisor stands
        down without writing under a stale term.

    Returns
    -------
    int
        Number of approval requests timed-out (and parent runs failed).
    """
    from ...models_automations import (
        AutomationApprovalRequest,
        AutomationRun,
    )

    now = datetime.now(UTC)

    stmt = (
        select(AutomationApprovalRequest.id, AutomationApprovalRequest.run_id)
        .where(AutomationApprovalRequest.expires_at.isnot(None))
        .where(AutomationApprovalRequest.expires_at < now)
        .where(AutomationApprovalRequest.resolved_at.is_(None))
        .limit(_BATCH_LIMIT)
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return 0

    swept = 0
    for request_id, run_id in rows:
        await _verify_lease_or_raise(db, current_term=current_term)

        ts = datetime.now(UTC)

        await db.execute(
            update(AutomationApprovalRequest)
            .where(AutomationApprovalRequest.id == request_id)
            .values(
                resolved_at=ts,
                response={"choice": "expired", "notes": "approval_timeout"},
            )
        )

        await db.execute(
            update(AutomationRun)
            .where(AutomationRun.id == run_id)
            .values(
                status="failed",
                ended_at=ts,
                paused_reason="approval_timeout",
                lease_term=current_term,
            )
        )

        swept += 1

    # Final lease verify before commit — keeps the same fencing
    # guarantee as the per-row check.
    await _verify_lease_or_raise(db, current_term=current_term)
    await db.commit()

    if swept:
        logger.info(
            "[APPROVAL-TIMEOUT-SWEEP] timed-out %d approval(s) at term=%d",
            swept,
            current_term,
        )
    return swept


async def _verify_lease_or_raise(db: AsyncSession, *, current_term: int) -> None:
    """Cheap in-TXN lease verify; raises :class:`LeaseLost` on mismatch.

    Mirrors :mod:`heartbeat_sweep` and :mod:`cron_producer`. Avoids
    ``FOR UPDATE`` because the sweep doesn't need to block other
    leaders — the verify is a fence, not a serializer.
    """
    from sqlalchemy import text

    row = (
        await db.execute(
            text("SELECT term FROM controller_leases WHERE name = 'controller'")
        )
    ).first()
    if row is None:
        raise LeaseLost("controller lease row missing")
    if int(row[0] or 0) != current_term:
        raise LeaseLost(
            f"lease term mismatch (db={row[0]} ours={current_term})"
        )


__all__ = ["sweep_expired_approvals"]
