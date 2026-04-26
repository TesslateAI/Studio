"""One-shot sweep when a controller becomes leader (Phase 4).

Catches the lost-fire window during fail-over: the previous leader
inserted ``automation_runs(status='queued')`` rows but its ARQ enqueue
either failed or was lost mid-flight. Re-enqueue every queued run older
than 60s with the same ``_job_id=str(event_id)`` — ARQ dedups, so a
healthy job that's still in the queue is unaffected.

Idempotency
-----------
The dispatcher uses ``UNIQUE(automation_id, event_id)`` on
``automation_runs`` so re-enqueueing the same event never produces a
duplicate run. The job-id collapse is belt-and-suspenders.

Why 60 seconds
--------------
The cron producer commits the run row before enqueueing — the worst
case is the producer crashed between commit and enqueue. ARQ ack-time
in the steady state is sub-second; 60s is a generous lower bound on
"this row is genuinely orphaned, not just slow."
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from uuid import UUID

from sqlalchemy import select

logger = logging.getLogger(__name__)


_STALE_SECONDS = 60


async def sweep_once(
    *,
    db_factory: Callable[[], Any],
    arq_pool: Any | None,
    current_term: int,
    stale_seconds: int = _STALE_SECONDS,
) -> int:
    """Re-enqueue stale queued runs. Returns the number of jobs enqueued.

    Marks each touched run with the new ``lease_term`` so subsequent
    inspections can correlate the recovery action with the leader that
    performed it.
    """
    from ...models_automations import AutomationEvent, AutomationRun

    cutoff = datetime.now(UTC) - timedelta(seconds=stale_seconds)
    stale: list[tuple[UUID, UUID]] = []

    async with db_factory() as db:
        stmt = (
            select(AutomationRun.id, AutomationRun.event_id, AutomationRun.automation_id)
            .where(AutomationRun.status == "queued")
            .where(AutomationRun.created_at < cutoff)
            .where(AutomationRun.event_id.isnot(None))
            .limit(500)
        )
        rows = (await db.execute(stmt)).all()
        if not rows:
            return 0

        for run_id, event_id, automation_id in rows:
            stale.append((automation_id, event_id))
            # Touch the lease_term so observability sees the takeover.
            await db.execute(
                AutomationRun.__table__.update()
                .where(AutomationRun.id == run_id)
                .values(lease_term=current_term)
            )

        # Touch the AutomationEvent so re-enqueue is observable.
        await db.execute(
            AutomationEvent.__table__.update()
            .where(AutomationEvent.id.in_([e for _, e in stale]))
            .where(AutomationEvent.dispatched_at.is_(None))
            .values(dispatched_at=datetime.now(UTC))
        )
        await db.commit()

    fired = 0
    for automation_id, event_id in stale:
        try:
            await _enqueue_dispatch(arq_pool, automation_id, event_id)
            fired += 1
        except Exception:
            logger.exception(
                "[SWEEP] failed to re-enqueue automation=%s event=%s",
                automation_id,
                event_id,
            )

    if fired:
        logger.info(
            "[SWEEP] re-enqueued %d stale queued run(s) at term=%d",
            fired,
            current_term,
        )
    return fired


async def _enqueue_dispatch(
    arq_pool: Any | None, automation_id: UUID, event_id: UUID
) -> None:
    args = (str(automation_id), str(event_id), "controller-sweep")
    job_id = str(event_id)

    if arq_pool is not None:
        await arq_pool.enqueue_job(
            "dispatch_automation_task",
            *args,
            _job_id=job_id,
        )
        return

    from ..task_queue import get_task_queue

    await get_task_queue().enqueue("dispatch_automation_task", *args)


__all__ = ["sweep_once"]
