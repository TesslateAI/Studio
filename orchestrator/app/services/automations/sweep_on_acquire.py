"""One-shot sweep when a controller becomes leader (Phase 4).

Catches the lost-fire window during fail-over: the previous leader
inserted ``automation_events`` rows but its ARQ enqueue of
``dispatch_automation_task`` either failed or was lost mid-flight.
Re-enqueue dispatch for every event whose ``dispatched_at IS NULL``
older than 60s, with the same ``_job_id=str(event_id)`` — ARQ dedups,
so a healthy in-flight job is unaffected.

Why events, not runs
--------------------
The dispatcher (``services.automations.dispatcher._upsert_run``) is
the *sole* creator of ``automation_runs`` rows. Cron / manual / webhook
/ gateway triggers all stop at writing the event; the dispatcher's
Phase A creates the run on first invocation. So ``automation_runs``
never exists for an event that hasn't been dispatched yet — the
recovery anchor has to be the event row, not a non-existent run row.

Idempotency
-----------
The dispatcher uses ``UNIQUE(automation_id, event_id)`` on
``automation_runs`` so re-enqueueing the same event never produces a
duplicate run. The ARQ job-id collapse is belt-and-suspenders.

Why 60 seconds
--------------
Cron / manual handlers commit the event row before enqueueing — the
worst case is the producer crashed between commit and enqueue. ARQ
ack-time in the steady state is sub-second; 60s is a generous lower
bound on "this event is genuinely orphaned, not just slow."
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
    """Re-enqueue dispatch for stale undispatched events.

    Returns the number of dispatch jobs enqueued. ``current_term`` is
    accepted for symmetry with the controller_main signature; the sweep
    itself relies on ARQ dedup + dispatcher idempotency rather than the
    lease term for correctness.
    """
    from ...models_automations import AutomationEvent

    cutoff = datetime.now(UTC) - timedelta(seconds=stale_seconds)
    stale: list[tuple[UUID, UUID]] = []

    async with db_factory() as db:
        stmt = (
            select(AutomationEvent.id, AutomationEvent.automation_id)
            .where(AutomationEvent.dispatched_at.is_(None))
            .where(AutomationEvent.failed_at.is_(None))
            .where(AutomationEvent.received_at < cutoff)
            .limit(500)
        )
        rows = (await db.execute(stmt)).all()
        if not rows:
            return 0

        for event_id, automation_id in rows:
            stale.append((automation_id, event_id))

        # Stamp dispatched_at so subsequent sweeps don't re-pick the same
        # rows. The dispatcher itself doesn't rely on this column for
        # correctness — it's an observability hook.
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
            "[SWEEP] re-enqueued %d stale undispatched event(s) at term=%d",
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
