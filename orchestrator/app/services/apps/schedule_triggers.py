"""Trigger event recovery sweep (Phase 1).

.. note::

   **This module is RECOVERY-ONLY post-Phase-1.** The hot path lives in
   :mod:`app.routers.app_triggers` (webhook ingest + ARQ enqueue in one
   request, ~ms latency). The drain function below catches the rare case
   where the handler INSERTed an ``automation_events`` row but crashed
   before the ARQ enqueue succeeded — the row is left with
   ``dispatched_at IS NULL`` and ``failed_at IS NULL``.

   The sweep is run periodically by the controller (Phase 4 spec) — for
   Phase 1 it can be invoked manually or wired in as an ARQ cron entry.
   With enqueue-only sync, the success path completes in single-digit ms,
   so a 5s ``received_at`` cutoff is a generous safety margin.

The legacy ``ingest_trigger_event`` that wrote to the dropped
``schedule_trigger_events`` table is gone. Use
:func:`app.services.automations.trigger_events.ingest_trigger_event` for
all new ingest sites.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models_automations import AutomationDefinition, AutomationEvent
from ..automations.trigger_events import mark_dispatched, mark_failed

__all__ = ["process_trigger_events_batch", "ingest_trigger_event"]

logger = logging.getLogger(__name__)

# Events younger than this are still in the live ingest path; ignore them
# so the sweep never races a healthy handler. Webhook handler success path
# is < 50ms in the happy case — 5 seconds is ~100x headroom.
_RECOVERY_GRACE = timedelta(seconds=5)


async def _arq_pool(ctx: dict[str, Any] | None) -> Any:
    """Resolve the ARQ pool from worker ctx, with a lazy fallback so this
    function can also be invoked from a one-shot CLI / health probe.
    """
    if isinstance(ctx, dict):
        pool = ctx.get("redis")
        if pool is not None:
            return pool
    try:
        from arq import create_pool

        from ...worker import _get_redis_settings  # type: ignore

        return await create_pool(_get_redis_settings())
    except Exception:
        logger.exception("schedule_triggers: failed to create arq pool")
        return None


async def process_trigger_events_batch(
    ctx: dict[str, Any] | None = None,
    *,
    limit: int = 100,
    grace: timedelta = _RECOVERY_GRACE,
) -> dict[str, int]:
    """Drain orphaned ``automation_events`` rows.

    Selects events where:

    * ``dispatched_at IS NULL`` (never reached the queue)
    * ``failed_at IS NULL``    (not already terminal)
    * ``received_at < now() - grace`` (older than the safety margin)

    Each row is locked with ``FOR UPDATE SKIP LOCKED`` so multiple
    controllers can sweep concurrently without duplicating work, and
    processed under its own savepoint so one bad row never poisons the
    batch.

    Returns ``{processed, failed, skipped}`` counters for observability.
    """
    from ...database import AsyncSessionLocal

    pool = await _arq_pool(ctx)
    processed = 0
    failed = 0
    skipped = 0

    cutoff = datetime.now(tz=UTC) - grace

    async with AsyncSessionLocal() as db:
        stmt = (
            select(AutomationEvent)
            .where(AutomationEvent.dispatched_at.is_(None))
            .where(AutomationEvent.failed_at.is_(None))
            .where(AutomationEvent.received_at < cutoff)
            .order_by(AutomationEvent.received_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        events = (await db.execute(stmt)).scalars().all()
        if not events:
            return {"processed": 0, "failed": 0, "skipped": 0}

        for event in events:
            savepoint = await db.begin_nested()
            try:
                automation = await _load_definition(db, event.automation_id)
                if automation is None or not automation.is_active:
                    await mark_failed(
                        db,
                        event.id,
                        "automation missing"
                        if automation is None
                        else "automation inactive",
                    )
                    skipped += 1
                    await savepoint.commit()
                    continue

                if pool is None:
                    await mark_failed(db, event.id, "no arq pool available")
                    failed += 1
                    await savepoint.commit()
                    continue

                worker_id = "trigger-recovery-sweep"
                await pool.enqueue_job(
                    "dispatch_automation_task",
                    str(event.automation_id),
                    str(event.id),
                    worker_id,
                    _job_id=str(event.id),
                )
                await mark_dispatched(db, event.id)
                processed += 1
                await savepoint.commit()
            except Exception as exc:  # pragma: no cover - defensive
                await savepoint.rollback()
                logger.exception(
                    "schedule_triggers.recovery failed event=%s", event.id
                )
                # Mark the row failed in a fresh savepoint so the next sweep
                # doesn't immediately retry the same broken row.
                sp2 = await db.begin_nested()
                try:
                    await mark_failed(db, event.id, repr(exc))
                    failed += 1
                    await sp2.commit()
                except Exception:
                    await sp2.rollback()

        await db.commit()

    logger.info(
        "schedule_triggers.recovery processed=%d failed=%d skipped=%d",
        processed,
        failed,
        skipped,
    )
    return {"processed": processed, "failed": failed, "skipped": skipped}


async def _load_definition(
    db: AsyncSession, automation_id: UUID
) -> AutomationDefinition | None:
    return (
        await db.execute(
            select(AutomationDefinition).where(
                AutomationDefinition.id == automation_id
            )
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Legacy shim — kept ONLY so out-of-tree callers that imported
# ``ingest_trigger_event`` from this module before the hard reset don't
# break their import. The ``schedule_id`` parameter is preserved as a
# best-effort field name; new code MUST use
# ``app.services.automations.trigger_events.ingest_trigger_event`` with the
# proper ``automation_id`` + ``trigger_id`` + ``trigger_kind`` arguments.
# ---------------------------------------------------------------------------


async def ingest_trigger_event(  # type: ignore[no-redef]  # legacy shim
    db: AsyncSession,
    *,
    schedule_id: UUID | None = None,
    automation_id: UUID | None = None,
    trigger_id: UUID | None = None,
    trigger_kind: str = "legacy",
    payload: dict[str, Any] | None = None,
) -> UUID:
    """Backward-compat wrapper around the post-reset ingest helper.

    The old signature accepted ``schedule_id`` (FK to the now-dropped
    ``agent_schedules`` table). Callers that still pass ``schedule_id``
    will fail at the database layer when the FK to
    ``automation_definitions`` rejects an unknown id — this shim does NOT
    fabricate the row, it only keeps the import alive long enough for
    legacy modules (``services/apps/db_event_dispatcher.py``) to be
    rewritten in a follow-up wave.
    """
    from ..automations.trigger_events import (
        ingest_trigger_event as _ingest_new,
    )

    if automation_id is None:
        if schedule_id is None:
            raise TypeError(
                "ingest_trigger_event: pass automation_id (preferred) or "
                "schedule_id (legacy)"
            )
        # Treat the schedule_id as the automation_id for the legacy bridge —
        # callers that haven't migrated will fail loudly at the FK check
        # instead of silently inserting an orphan row.
        automation_id = schedule_id

    return await _ingest_new(
        db,
        automation_id=automation_id,
        trigger_id=trigger_id,
        trigger_kind=trigger_kind,
        payload=payload or {},
    )
