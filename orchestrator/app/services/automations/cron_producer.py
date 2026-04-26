"""Controller-plane cron producer (Phase 4).

Moved out of :mod:`app.services.gateway.scheduler` (which keeps a
backward-compat shim until the gateway loop is fully retired).

Algorithm
---------
Per tick the producer:

1. Selects due ``automation_triggers`` rows
   ``WHERE kind='cron' AND is_active=true AND next_run_at<=now()``
   with ``FOR UPDATE SKIP LOCKED`` on Postgres (no-op on SQLite).

2. For each, in **one transaction with the lease verify**:

   * ``SELECT term FROM controller_leases WHERE name='controller'
     FOR UPDATE`` → assert returned term == our term, else raise
     :class:`LeaseLost` so the caller can stand down.
   * Compute next ``next_run_at`` via :mod:`croniter`.
   * INSERT an ``automation_events`` row with
     ``idempotency_key='cron:{trigger_id}:{tick_iso}'``.
   * INSERT an ``automation_runs`` row with ``status='queued'``,
     ``lease_term=current_term``, ``retry_count=0``,
     ``heartbeat_at=now()``.
   * UPDATE the trigger's ``next_run_at`` and ``last_run_at``.
   * COMMIT.

3. After commit (so the worker always sees the queued row), enqueue
   ``dispatch_automation_task`` to ARQ with
   ``_job_id=str(event_id)`` for ARQ-side dedup.

Lease fencing
-------------
Step 2's lease verify is the load-bearing TOCTOU defence: if the leader
was deposed between the start of the tick and the INSERT, the verify
fails and the whole batch rolls back — no phantom queued runs from a
ghost leader.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from sqlalchemy import or_, select, text

from .intents import LeaseLost

logger = logging.getLogger(__name__)


_TICK_INTERVAL_SECONDS = 60
_MAX_BATCH = 100


async def run_loop(
    *,
    db_factory: Callable[[], Any],
    arq_pool: Any | None,
    lease_backend: Any,
    token_provider: Callable[[], Any],
    shutdown_event: asyncio.Event,
    interval_seconds: int = _TICK_INTERVAL_SECONDS,
) -> None:
    """Tick the cron producer until ``shutdown_event`` fires.

    Errors inside a single tick are logged and swallowed so a transient
    DB blip doesn't kill leadership. Hard errors (e.g., lease lost)
    propagate via the shutdown event mechanism in ``controller_main``.
    """
    logger.info("[CRON-PROD] starting (interval=%ds)", interval_seconds)

    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(
                shutdown_event.wait(), timeout=interval_seconds
            )
            return
        except TimeoutError:
            pass

        try:
            current_term = int(token_provider().term)
            await tick(
                db_factory=db_factory,
                arq_pool=arq_pool,
                current_term=current_term,
            )
        except LeaseLost:
            logger.warning("[CRON-PROD] lease lost mid-tick; standing down")
            return
        except Exception:
            logger.exception("[CRON-PROD] tick failed")


async def tick(
    *,
    db_factory: Callable[[], Any],
    arq_pool: Any | None,
    current_term: int,
    now: datetime | None = None,
) -> int:
    """Execute one tick, returning the number of automations enqueued."""
    if now is None:
        now = datetime.now(UTC)

    # Lazy import — avoids module-load surface in tests.
    from ...models_automations import (
        AutomationDefinition,
        AutomationEvent,
        AutomationRun,
        AutomationTrigger,
    )

    enqueue_jobs: list[tuple[UUID, UUID]] = []

    async with db_factory() as db:
        bind = db.get_bind() if hasattr(db, "get_bind") else None
        dialect = getattr(getattr(bind, "dialect", None), "name", "") if bind else ""
        use_for_update = dialect == "postgresql"

        # --------------------------------------------------------------
        # Lease verify — must run inside this same TXN.
        # --------------------------------------------------------------
        if use_for_update:
            row = (
                await db.execute(
                    text(
                        "SELECT term FROM controller_leases "
                        "WHERE name = 'controller' FOR UPDATE"
                    )
                )
            ).first()
        else:
            row = (
                await db.execute(
                    text(
                        "SELECT term FROM controller_leases "
                        "WHERE name = 'controller'"
                    )
                )
            ).first()

        if row is None:
            raise LeaseLost("controller lease row missing")
        if int(row[0] or 0) != current_term:
            raise LeaseLost(
                f"lease term mismatch (db={row[0]} ours={current_term})"
            )

        # --------------------------------------------------------------
        # Claim due triggers.
        # --------------------------------------------------------------
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
            .order_by(AutomationTrigger.next_run_at.asc())
            .limit(_MAX_BATCH)
        )
        if use_for_update:
            stmt = stmt.with_for_update(skip_locked=True, of=AutomationTrigger)

        rows = (await db.execute(stmt)).all()

        if not rows:
            await db.commit()
            return 0

        for trigger, automation in rows:
            cfg = trigger.config or {}
            cron_expr = cfg.get("cron_expression") or cfg.get("expression")
            if not cron_expr:
                logger.warning(
                    "[CRON-PROD] trigger %s has no cron_expression; deactivating",
                    trigger.id,
                )
                trigger.is_active = False
                continue

            tz_name = cfg.get("timezone") or "UTC"
            try:
                tz = ZoneInfo(tz_name) if tz_name != "UTC" else UTC
            except (ZoneInfoNotFoundError, KeyError, ValueError):
                logger.warning(
                    "[CRON-PROD] trigger %s has invalid timezone %r; deactivating",
                    trigger.id,
                    tz_name,
                )
                trigger.is_active = False
                continue

            try:
                local_now = now.astimezone(tz)
                iter_ = croniter(cron_expr, local_now)
                new_next_local = iter_.get_next(datetime)
                if new_next_local.tzinfo is None:
                    new_next_local = new_next_local.replace(tzinfo=tz)
                new_next = new_next_local.astimezone(UTC)
            except (ValueError, KeyError) as exc:
                logger.warning(
                    "[CRON-PROD] trigger %s has malformed cron %r (%s); deactivating",
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
            tick_iso = now.replace(microsecond=0).isoformat()
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
                        "kind": "cron",
                    },
                    idempotency_key=f"cron:{trigger.id}:{tick_iso}",
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
                    lease_term=current_term,
                    heartbeat_at=now,
                )
            )
            enqueue_jobs.append((automation.id, event_id))

        await db.commit()

    # ------------------------------------------------------------------
    # Post-commit: enqueue ARQ jobs.
    # ------------------------------------------------------------------
    if not enqueue_jobs:
        return 0

    fired = 0
    for automation_id, event_id in enqueue_jobs:
        try:
            await _enqueue_dispatch(arq_pool, automation_id, event_id)
            fired += 1
        except Exception:
            logger.exception(
                "[CRON-PROD] failed to enqueue dispatch automation=%s event=%s",
                automation_id,
                event_id,
            )

    if fired:
        logger.info("[CRON-PROD] tick fired %d automation(s)", fired)
    return fired


async def _enqueue_dispatch(
    arq_pool: Any | None, automation_id: UUID, event_id: UUID
) -> None:
    """Enqueue ``dispatch_automation_task`` (ARQ in cloud, local in desktop).

    Uses ``_job_id=str(event_id)`` so a duplicate enqueue against the same
    event collapses to a single ARQ job. Belt-and-suspenders against the
    UNIQUE(automation_id, event_id) the dispatcher itself checks.
    """
    args = (str(automation_id), str(event_id), "controller-cron")
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


__all__ = ["run_loop", "tick"]
