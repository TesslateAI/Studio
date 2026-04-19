"""Schedule trigger ingestion + draining worker.

Two separate entrypoints:

* :func:`ingest_trigger_event` — inserts a row into
  ``schedule_trigger_events``. Fast, single INSERT; safe to call from
  webhook handlers.
* :func:`process_trigger_events_batch` — periodic sweep that dispatches
  queued events to the agent worker via ARQ. Uses ``SELECT ... FOR UPDATE
  SKIP LOCKED`` so multiple worker pods can drain the queue concurrently
  without duplicating work. Each row is processed in its own savepoint so
  one failure does not poison the batch.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentSchedule, Project, ScheduleTriggerEvent

__all__ = ["ingest_trigger_event", "process_trigger_events_batch"]

logger = logging.getLogger(__name__)


async def ingest_trigger_event(
    db: AsyncSession,
    *,
    schedule_id: UUID,
    payload: dict,
) -> UUID:
    """Insert a trigger event row. Returns the row id."""
    event_id = uuid.uuid4()
    db.add(
        ScheduleTriggerEvent(
            id=event_id,
            schedule_id=schedule_id,
            payload=payload or {},
        )
    )
    await db.flush()
    logger.info("schedule_trigger.ingest event=%s schedule=%s", event_id, schedule_id)
    return event_id


async def _build_agent_payload(
    db: AsyncSession,
    *,
    schedule: AgentSchedule,
    event: ScheduleTriggerEvent,
) -> dict[str, Any] | None:
    """Assemble the execute_agent_task payload for a single trigger event."""
    proj = (
        await db.execute(select(Project).where(Project.id == schedule.project_id))
    ).scalar_one_or_none()
    if proj is None:
        return None

    # Render a minimal prompt by appending payload context. Full templating
    # (a la the cron scheduler) lives in gateway/scheduler.py; triggers just
    # inject the raw payload under a known key for the agent to inspect.
    prompt = schedule.prompt_template or ""
    return {
        "task_id": str(uuid.uuid4()),
        "user_id": str(schedule.user_id),
        "project_id": str(schedule.project_id),
        "project_slug": proj.slug,
        "chat_id": None,
        "message": prompt,
        "agent_id": str(schedule.agent_id) if schedule.agent_id else None,
        "gateway_deliver": schedule.deliver,
        "session_key": None,
        "schedule_id": str(schedule.id),
        "trigger_event_id": str(event.id),
        "trigger_kind": schedule.trigger_kind,
        "trigger_payload": event.payload or {},
    }


async def _arq_pool(ctx: dict):
    """Resolve the ARQ pool from worker ctx, with a lazy fallback."""
    pool = ctx.get("redis") if isinstance(ctx, dict) else None
    if pool is not None:
        return pool
    try:
        from arq import create_pool

        from ...worker import _get_redis_settings  # type: ignore

        return await create_pool(_get_redis_settings())
    except Exception:
        logger.exception("schedule_trigger: failed to create arq pool")
        return None


async def process_trigger_events_batch(
    ctx: dict,
    *,
    limit: int = 100,
) -> dict:
    """Drain up to ``limit`` unprocessed trigger events."""
    from ...database import AsyncSessionLocal

    pool = await _arq_pool(ctx)
    processed = 0
    failed = 0
    skipped = 0

    async with AsyncSessionLocal() as db:
        stmt = (
            select(ScheduleTriggerEvent)
            .where(ScheduleTriggerEvent.processed_at.is_(None))
            .order_by(ScheduleTriggerEvent.received_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        events = (await db.execute(stmt)).scalars().all()
        if not events:
            return {"processed": 0, "failed": 0, "skipped": 0}

        for event in events:
            savepoint = await db.begin_nested()
            try:
                schedule = (
                    await db.execute(
                        select(AgentSchedule).where(AgentSchedule.id == event.schedule_id)
                    )
                ).scalar_one_or_none()
                if schedule is None or not schedule.is_active:
                    event.processed_at = datetime.now(tz=UTC)
                    event.result_status = "skipped"
                    event.error = "schedule missing" if schedule is None else "schedule inactive"
                    skipped += 1
                    await savepoint.commit()
                    continue

                if pool is None:
                    event.processed_at = datetime.now(tz=UTC)
                    event.result_status = "failed"
                    event.error = "no arq pool available"
                    failed += 1
                    await savepoint.commit()
                    continue

                # App-instance schedules go through a dedicated dispatcher
                # (Thread D) — V1Job or HTTP POST against the primary
                # container rather than an agent chat run.
                if schedule.app_instance_id is not None:
                    await pool.enqueue_job(
                        "invoke_app_instance_task",
                        str(schedule.id),
                        str(event.id),
                        event.payload or {},
                    )
                    event.processed_at = datetime.now(tz=UTC)
                    event.result_status = "enqueued"
                    event.error = None
                    processed += 1
                    await savepoint.commit()
                    continue

                payload = await _build_agent_payload(db, schedule=schedule, event=event)
                if payload is None:
                    event.processed_at = datetime.now(tz=UTC)
                    event.result_status = "failed"
                    event.error = "project not found"
                    failed += 1
                    await savepoint.commit()
                    continue

                await pool.enqueue_job("execute_agent_task", payload)
                event.processed_at = datetime.now(tz=UTC)
                event.result_status = "enqueued"
                event.error = None
                processed += 1
                await savepoint.commit()
            except Exception as exc:  # pragma: no cover - defensive
                await savepoint.rollback()
                logger.exception("schedule_trigger.process failed event=%s", event.id)
                # Mark the row failed in a fresh savepoint so we don't retry it
                # immediately in the next sweep with the same error.
                sp2 = await db.begin_nested()
                try:
                    event.processed_at = datetime.now(tz=UTC)
                    event.result_status = "failed"
                    event.error = repr(exc)[:1000]
                    failed += 1
                    await sp2.commit()
                except Exception:
                    await sp2.rollback()

        await db.commit()

    logger.info(
        "schedule_trigger.batch processed=%d failed=%d skipped=%d",
        processed,
        failed,
        skipped,
    )
    return {"processed": processed, "failed": failed, "skipped": skipped}
