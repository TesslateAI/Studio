"""
Cron Producer — tick-based cron trigger dispatcher.

Phase 1 of the OpenSail Automation Runtime. Operates on
``automation_triggers`` (kind='cron') joined to ``automation_definitions``,
materializes an ``AutomationEvent`` + ``AutomationRun(status='queued')``
in a single transaction, then enqueues ``dispatch_automation_task`` to ARQ.

The legacy ``agent_schedules`` table was dropped by alembic 0074; this
module replaces the previous schedule dispatcher.

Concurrency model
-----------------
The gateway runner is pinned to a single replica via the existing file lock
+ K8s ``Recreate`` strategy. The SQL claim still uses ``SELECT ... FOR UPDATE
SKIP LOCKED`` so two pods racing the same tick remain correct. Phase 4 will
move this loop into a dedicated ``automations-controller`` Deployment with
proper leader election.

The ARQ enqueue happens **after** ``commit()`` so the durable
``AutomationRun(status='queued')`` row is visible before the dispatcher
worker can pick it up. If the enqueue fails, the row is left in 'queued'
state for the Phase 4 controller's sweep-on-acquire to re-enqueue.
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from sqlalchemy import or_, select

logger = logging.getLogger(__name__)


class CronScheduler:
    """File-lock-protected cron producer for ``automation_triggers``."""

    def __init__(self, lock_dir: str = "/var/run/tesslate"):
        self._running = False
        self._lock_dir = lock_dir

    async def tick(self, db_factory, arq_pool) -> int:
        """
        Execute one scheduler tick.

        File-lock protected (non-blocking, skip if held).
        Returns the number of automations fired.
        """
        lock_path = os.path.join(self._lock_dir, "cron-tick.lock")
        Path(self._lock_dir).mkdir(parents=True, exist_ok=True)

        fd = None
        try:
            fd = open(lock_path, "w")  # noqa: SIM115 — must stay open for lock duration
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if fd:
                fd.close()
            return 0  # Another tick is running

        try:
            async with db_factory() as db:
                return await cron_tick(db, arq_pool)
        except Exception:
            logger.exception("[CRON] Tick error")
            return 0
        finally:
            if fd:
                fcntl.flock(fd, fcntl.LOCK_UN)
                fd.close()

    async def run_loop(self, db_factory, arq_pool, interval: int = 60) -> None:
        """Run the tick loop until stopped."""
        self._running = True
        logger.info("[CRON] Scheduler started (interval=%ds)", interval)

        while self._running:
            try:
                count = await self.tick(db_factory, arq_pool)
                if count:
                    logger.info("[CRON] Tick fired %d automation(s)", count)
            except Exception:
                logger.exception("[CRON] Tick loop error")
            await asyncio.sleep(interval)

    def stop(self) -> None:
        """Signal the run loop to stop."""
        self._running = False


async def cron_tick(db, arq_pool, now: datetime | None = None) -> int:
    """Claim due cron triggers, advance ``next_run_at``, persist event+run, enqueue.

    Operates inside the caller-provided async ``db`` session. Returns the
    number of automations whose ARQ jobs were successfully enqueued.

    Concurrency: ``SELECT ... FOR UPDATE SKIP LOCKED`` (Postgres) makes this
    safe against parallel callers. SQLite has no row-level locking; it relies
    on the gateway file-lock above for single-writer correctness, which is
    fine for desktop-mode single-process operation.

    The transaction commits **before** ARQ enqueue so the dispatcher worker
    always finds the ``AutomationRun(status='queued')`` row when it picks
    the job up. Enqueue failure leaves the row in 'queued' for the Phase 4
    controller's sweep-on-acquire to recover.
    """
    from ...models_automations import (
        AutomationDefinition,
        AutomationEvent,
        AutomationRun,
        AutomationTrigger,
    )

    if now is None:
        now = datetime.now(UTC)

    # SQLite (desktop) doesn't support FOR UPDATE / SKIP LOCKED. Detect via
    # the bind dialect and degrade gracefully — the file-lock + single-writer
    # gateway pod keeps correctness on that path.
    bind = db.get_bind() if hasattr(db, "get_bind") else None
    dialect_name = getattr(getattr(bind, "dialect", None), "name", "") if bind else ""
    use_skip_locked = dialect_name == "postgresql"

    stmt = (
        select(AutomationTrigger, AutomationDefinition)
        .join(
            AutomationDefinition,
            AutomationDefinition.id == AutomationTrigger.automation_id,
        )
        .where(AutomationTrigger.kind == "cron")
        .where(AutomationTrigger.is_active.is_(True))
        .where(AutomationDefinition.is_active.is_(True))
        .where(
            or_(
                AutomationTrigger.next_run_at.is_(None),
                AutomationTrigger.next_run_at <= now,
            )
        )
        # NULL ordering varies by dialect; correctness lives in the WHERE
        # clause, ordering is best-effort fairness only.
        .order_by(AutomationTrigger.next_run_at.asc())
        .limit(100)
    )
    if use_skip_locked:
        stmt = stmt.with_for_update(skip_locked=True, of=AutomationTrigger)

    rows = (await db.execute(stmt)).all()
    if not rows:
        return 0

    enqueue_jobs: list[tuple[UUID, UUID]] = []

    for trigger, automation in rows:
        cfg = trigger.config or {}
        cron_expr = cfg.get("cron_expression") or cfg.get("expression")
        if not cron_expr:
            logger.warning(
                "[CRON] trigger %s has no cron_expression in config; deactivating",
                trigger.id,
            )
            trigger.is_active = False
            continue

        # Resolve timezone. Invalid → log + deactivate (do not fire).
        tz_name = cfg.get("timezone") or "UTC"
        try:
            tz = ZoneInfo(tz_name) if tz_name != "UTC" else UTC
        except (ZoneInfoNotFoundError, KeyError, ValueError):
            logger.warning(
                "[CRON] trigger %s has invalid timezone %r; deactivating",
                trigger.id,
                tz_name,
            )
            trigger.is_active = False
            continue

        # Validate + compute next_run_at via croniter in the trigger's tz.
        try:
            local_now = now.astimezone(tz)
            iter_ = croniter(cron_expr, local_now)
            new_next_local = iter_.get_next(datetime)
            # Normalize back to UTC for storage.
            if new_next_local.tzinfo is None:
                new_next_local = new_next_local.replace(tzinfo=tz)
            new_next = new_next_local.astimezone(UTC)
        except (ValueError, KeyError) as exc:
            logger.warning(
                "[CRON] trigger %s has malformed cron expression %r (%s); deactivating",
                trigger.id,
                cron_expr,
                exc,
            )
            trigger.is_active = False
            continue

        trigger.next_run_at = new_next
        trigger.last_run_at = now

        event_id = uuid4()
        run_id = uuid4()
        db.add(
            AutomationEvent(
                id=event_id,
                automation_id=automation.id,
                trigger_id=trigger.id,
                trigger_kind="cron",
                payload={
                    "fired_at": now.isoformat(),
                    "cron_expression": cron_expr,
                    "timezone": tz_name,
                },
                received_at=now,
            )
        )
        db.add(
            AutomationRun(
                id=run_id,
                automation_id=automation.id,
                event_id=event_id,
                status="queued",
                retry_count=0,
            )
        )
        enqueue_jobs.append((automation.id, event_id))

    # Commit BEFORE enqueue: the dispatcher worker MUST see the queued run
    # row when it pops the ARQ job. If the commit fails, we re-raise (no
    # phantom enqueues against rolled-back state).
    await db.commit()

    if not enqueue_jobs:
        return 0

    fired = 0
    for automation_id, event_id in enqueue_jobs:
        try:
            await _enqueue_dispatch(arq_pool, automation_id, event_id)
            fired += 1
        except Exception:
            logger.exception(
                "[CRON] Failed to enqueue dispatch automation=%s event=%s "
                "(row left in 'queued' for controller sweep)",
                automation_id,
                event_id,
            )

    return fired


async def _enqueue_dispatch(arq_pool, automation_id: UUID, event_id: UUID) -> None:
    """Enqueue ``dispatch_automation_task`` to ARQ (or local queue on desktop).

    Uses ``_job_id=str(event_id)`` so duplicate ticks against the same event
    collapse to a single ARQ job (ARQ's own idempotency primitive). The
    dispatcher itself has a stronger ``UNIQUE (automation_id, event_id)``
    guarantee, so this is defense-in-depth.
    """
    args = (str(automation_id), str(event_id), "cron-tick")
    job_id = str(event_id)

    if arq_pool is not None:
        await arq_pool.enqueue_job(
            "dispatch_automation_task",
            *args,
            _job_id=job_id,
        )
        return

    # Desktop / no-Redis fallback — go through the in-process task queue.
    from ..task_queue import get_task_queue

    await get_task_queue().enqueue("dispatch_automation_task", *args)


def compute_next_run(normalized_cron: str, after: datetime | None = None) -> datetime:
    """Compute the next run time from a normalized cron expression.

    Kept for back-compat with legacy callers in ``routers/schedules.py`` and
    ``agent/tools/schedule_ops/manage_schedule.py`` that still import this
    symbol. Those modules also reference the dropped ``agent_schedules``
    table and are slated for removal under the Phase 1 hard reset; this
    helper is preserved purely so the imports do not break collection in
    the meantime.
    """
    base = after or datetime.now(UTC)
    return croniter(normalized_cron, base).get_next(datetime)


__all__ = ["CronScheduler", "compute_next_run", "cron_tick"]
