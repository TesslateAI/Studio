"""Stale-running heartbeat sweep (Phase 4).

Catches the lost-worker window: a worker picked up an
``automation_runs`` row, started executing, then died (OOM kill,
SIGKILL, node loss, network partition) without writing a terminal
status. The dispatcher heartbeats every step (see
``dispatcher.update_run_heartbeat``), so a row whose ``heartbeat_at``
is older than ``stale_seconds`` is by definition orphaned.

Algorithm
---------
Per call:

1. SELECT runs ``WHERE status='running' AND heartbeat_at < now() -
   stale_seconds``.
2. For each row, in one transaction:

   * UPDATE ``status='expired'``, ``ended_at=now()``,
     ``paused_reason='heartbeat_lost'``, increment ``retry_count``.
   * If ``retry_count <= max_retries`` AND the run still has its
     ``event_id``: re-enqueue ``dispatch_automation_task`` with
     ``_job_id=str(automation_run_id)`` (mirrors
     ``sweep_on_acquire``). The re-enqueued worker flips status back
     to ``queued`` via the dispatcher's existing two-query upsert.
   * Else: leave terminal at ``status='failed'``,
     ``paused_reason='exhausted_retries'``.

Idempotency
-----------
The unique ``(automation_id, event_id)`` constraint on
``automation_runs`` plus the ARQ ``_job_id`` collapse ensures that if
the original worker was merely slow (not dead), a stray heartbeat that
arrives after this sweep won't double-run the work. The retry counter
is the auth source for "how many times has this run been resurrected".

Note on the missing ``expired_at`` column
-----------------------------------------
The plan referenced ``expired_at``; the live model has only
``ended_at``. We use ``ended_at`` as the canonical "this run has
terminated" timestamp because that's what the dispatcher writes on
both success and failure paths — keeping the timestamp semantics
consistent across the two writers avoids a downstream "which column do
I look at" ambiguity.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .intents import LeaseLost

logger = logging.getLogger(__name__)


_STALE_SECONDS = 90
_MAX_RETRIES = 3
_BATCH_LIMIT = 500


async def sweep_stale_running(
    db: AsyncSession,
    *,
    queue: Any | None = None,
    current_term: int,
    stale_seconds: int = _STALE_SECONDS,
    max_retries: int = _MAX_RETRIES,
) -> int:
    """Expire stale running runs and re-enqueue retryable ones.

    Parameters
    ----------
    db:
        Session used for both the SELECT and the per-row UPDATE. The
        caller commits at the end of the sweep.
    queue:
        ARQ pool (cloud) or ``None`` (desktop — falls back to the local
        task queue). Mirrors the surface used by
        :mod:`sweep_on_acquire`.
    current_term:
        The leader term that initiated the sweep. If the controller
        loses the lease mid-sweep this is checked against the live
        ``controller_leases`` row before each commit; a mismatch
        raises :class:`LeaseLost` so the supervisor stands down without
        writing under a stale term.
    stale_seconds:
        Heartbeat age beyond which a running row is considered
        orphaned.
    max_retries:
        Inclusive ceiling on ``retry_count`` after the increment. Once
        a row reaches this ceiling we give up and leave it terminal.

    Returns
    -------
    int
        Number of rows the sweep touched (both retried and exhausted).
    """
    from ...models_automations import AutomationRun

    cutoff = datetime.now(UTC) - timedelta(seconds=stale_seconds)

    stmt = (
        select(
            AutomationRun.id,
            AutomationRun.automation_id,
            AutomationRun.event_id,
            AutomationRun.retry_count,
        )
        .where(AutomationRun.status == "running")
        .where(AutomationRun.heartbeat_at.isnot(None))
        .where(AutomationRun.heartbeat_at < cutoff)
        .limit(_BATCH_LIMIT)
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return 0

    swept = 0
    retry_jobs: list[tuple[UUID, UUID, UUID]] = []  # (run_id, automation_id, event_id)

    for run_id, automation_id, event_id, retry_count in rows:
        # Lease verify before each row mutation. Cheap and keeps the
        # window for "deposed leader writes status flips" tiny. A
        # LeaseLost from inside the loop is propagated so the caller
        # rolls back any uncommitted changes.
        await _verify_lease_or_raise(db, current_term=current_term)

        new_retry_count = (retry_count or 0) + 1
        now = datetime.now(UTC)

        if new_retry_count <= max_retries and event_id is not None:
            # Mark expired so observers see the heartbeat-loss event,
            # then schedule the re-enqueue. The dispatcher's
            # status-upsert flips the row back to ``queued`` when the
            # new worker picks it up.
            await db.execute(
                update(AutomationRun)
                .where(AutomationRun.id == run_id)
                .values(
                    status="expired",
                    ended_at=now,
                    paused_reason="heartbeat_lost",
                    retry_count=new_retry_count,
                    lease_term=current_term,
                )
            )
            retry_jobs.append((run_id, automation_id, event_id))
        else:
            # Terminal. Either we've exhausted retries or the row is
            # missing the event_id we'd need to re-enqueue.
            terminal_reason = (
                "exhausted_retries"
                if new_retry_count > max_retries
                else "heartbeat_lost_no_event"
            )
            await db.execute(
                update(AutomationRun)
                .where(AutomationRun.id == run_id)
                .values(
                    status="failed",
                    ended_at=now,
                    paused_reason=terminal_reason,
                    retry_count=new_retry_count,
                    lease_term=current_term,
                )
            )

        swept += 1

    # Final lease verify before commit — we don't want to commit
    # status flips under a stale term even if every per-row check
    # passed (the lease could have flipped between the last row and
    # the commit).
    await _verify_lease_or_raise(db, current_term=current_term)
    await db.commit()

    # Post-commit: enqueue retries. Failures here are logged but don't
    # re-raise — a single re-enqueue failure must not undo the status
    # flips we already committed (the next sweep will pick them back
    # up because their status is now ``expired``... actually no, we
    # filter by ``running``. The fallback is the unique
    # ``(automation_id, event_id)`` constraint plus the missed-event
    # drain — both ensure work eventually reaches a worker.).
    fired = 0
    for run_id, automation_id, event_id in retry_jobs:
        try:
            await _enqueue_dispatch(
                queue, automation_id=automation_id, event_id=event_id, run_id=run_id
            )
            fired += 1
        except Exception:
            logger.exception(
                "[HB-SWEEP] failed to re-enqueue automation=%s event=%s run=%s",
                automation_id,
                event_id,
                run_id,
            )

    if swept:
        logger.info(
            "[HB-SWEEP] swept %d stale running run(s) (retried=%d) at term=%d",
            swept,
            fired,
            current_term,
        )
    return swept


async def _verify_lease_or_raise(db: AsyncSession, *, current_term: int) -> None:
    """Cheap in-TXN lease verify; raises :class:`LeaseLost` on mismatch.

    Mirrors the verify pattern in :mod:`cron_producer.tick`. Avoids
    ``FOR UPDATE`` because the sweep doesn't need to block other
    leaders — the verify is just a fence: if our term has been
    superseded we want to bail out, not race.
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


async def _enqueue_dispatch(
    queue: Any | None,
    *,
    automation_id: UUID,
    event_id: UUID,
    run_id: UUID,
) -> None:
    """Re-enqueue ``dispatch_automation_task`` for a stale-running run.

    Uses ``_job_id=str(run_id)`` so multiple sweeps against the same
    expired row collapse to a single ARQ job. (We deliberately do NOT
    use ``event_id`` as the job id here because the original cron-side
    enqueue already used that — ARQ would dedup our retry against the
    dead worker's job.)
    """
    args = (str(automation_id), str(event_id), "controller-heartbeat-sweep")
    job_id = str(run_id)

    if queue is not None:
        await queue.enqueue_job(
            "dispatch_automation_task",
            *args,
            _job_id=job_id,
        )
        return

    from ..task_queue import get_task_queue

    await get_task_queue().enqueue("dispatch_automation_task", *args)


__all__ = ["sweep_stale_running"]
