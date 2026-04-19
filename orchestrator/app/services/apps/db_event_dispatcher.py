"""DB event dispatcher (Wave 9 Track D1).

ARQ cron task that drains ``tesslate:db_events:*`` Redis Streams and
fans the events out to ``AgentSchedule`` rows whose ``trigger_kind`` is
``db_event``. Matches happen on::

    trigger_config->>'table' == event.table

For every match we insert a ``ScheduleTriggerEvent`` row; the existing
``process_schedule_triggers_cron`` worker (FOR UPDATE SKIP LOCKED) drains
those into actual agent runs.

This wave inserts no ``db_event`` schedules, so the dispatcher is a
correct no-op in production. Wave 10 lights it up.

Operational notes:
  * Discovery scans stream keys via ``SCAN`` with the ``DB_EVENT_STREAM_PREFIX``
    pattern. Cheap when there are no streams.
  * Consumer group ``db_event_dispatcher`` is created lazily per stream
    (``MKSTREAM`` style) so a fresh deploy works without prep.
  * Bounded batch (``COUNT`` per stream) so a runaway producer can't starve
    other crons. Unprocessed entries stay in PEL and are retried next tick.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from ...models import AgentSchedule
from .event_bus import DB_EVENT_STREAM_PREFIX
from .schedule_triggers import ingest_trigger_event

logger = logging.getLogger(__name__)

CONSUMER_GROUP = "db_event_dispatcher"
CONSUMER_NAME = "worker"
BATCH_PER_STREAM = 100
SCAN_BATCH = 200

__all__ = ["db_event_dispatcher"]


async def _discover_streams(redis) -> list[str]:
    streams: list[str] = []
    cursor = 0
    pattern = f"{DB_EVENT_STREAM_PREFIX}*"
    while True:
        cursor, batch = await redis.scan(cursor=cursor, match=pattern, count=SCAN_BATCH)
        for key in batch:
            streams.append(key.decode() if isinstance(key, bytes) else key)
        if cursor == 0:
            break
    return streams


async def _ensure_group(redis, stream: str) -> None:
    try:
        await redis.xgroup_create(stream, CONSUMER_GROUP, id="0", mkstream=True)
    except Exception as exc:  # noqa: BLE001
        # BUSYGROUP just means it already exists. Anything else is logged
        # but non-fatal — we'll try again next tick.
        msg = str(exc)
        if "BUSYGROUP" not in msg:
            logger.debug("xgroup_create(%s) noop: %s", stream, msg)


def _decode_event(fields: dict[Any, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in fields.items():
        key = k.decode() if isinstance(k, bytes) else k
        val = v.decode() if isinstance(v, bytes) else v
        out[key] = val
    return out


async def _fanout_event(db, evt: dict[str, str]) -> int:
    """Insert ScheduleTriggerEvent rows for every matching db_event schedule.

    Returns the number of trigger events inserted.
    """
    table = evt.get("table") or ""
    tenant_id = evt.get("tenant_id") or None

    # Match on trigger_kind + trigger_config->>'table'. Tenant filter is
    # advisory: a schedule explicitly scoped to a different user/team
    # should not fire. We compare against AgentSchedule.user_id since that
    # is the only universally populated owner column today.
    stmt = select(AgentSchedule).where(
        AgentSchedule.trigger_kind == "db_event",
        AgentSchedule.is_active.is_(True),
        AgentSchedule.trigger_config["table"].astext == table,
    )
    result = await db.execute(stmt)
    matches = result.scalars().all()

    inserted = 0
    for sched in matches:
        if tenant_id and str(sched.user_id) != tenant_id:
            # Schedule belongs to a different owner. Skip rather than leak
            # cross-tenant row events into a foreign agent run.
            continue
        await ingest_trigger_event(
            db,
            schedule_id=sched.id,
            payload={"db_event": evt},
        )
        inserted += 1
    return inserted


async def db_event_dispatcher(ctx: dict) -> dict:
    """ARQ cron entrypoint. Drains all db_event streams once."""
    from ...database import AsyncSessionLocal
    from ..cache_service import get_redis_client

    redis = await get_redis_client()
    if not redis:
        return {"streams": 0, "events": 0, "inserted": 0}

    try:
        streams = await _discover_streams(redis)
    except Exception:
        logger.exception("db_event_dispatcher: stream discovery failed")
        return {"streams": 0, "events": 0, "inserted": 0, "error": True}

    if not streams:
        return {"streams": 0, "events": 0, "inserted": 0}

    total_events = 0
    total_inserted = 0

    for stream in streams:
        await _ensure_group(redis, stream)
        try:
            entries = await redis.xreadgroup(
                CONSUMER_GROUP,
                CONSUMER_NAME,
                {stream: ">"},
                count=BATCH_PER_STREAM,
                block=0,
            )
        except Exception:
            logger.exception("db_event_dispatcher: xreadgroup(%s) failed", stream)
            continue

        if not entries:
            continue

        # entries shape: [(stream_name, [(id, fields), ...])]
        ack_ids: list[str] = []
        async with AsyncSessionLocal() as db:
            for _stream_name, items in entries:
                for entry_id, fields in items:
                    total_events += 1
                    evt = _decode_event(fields)
                    try:
                        total_inserted += await _fanout_event(db, evt)
                        ack_ids.append(
                            entry_id.decode() if isinstance(entry_id, bytes) else entry_id
                        )
                    except Exception:
                        logger.exception(
                            "db_event_dispatcher: fanout failed for %s on %s",
                            entry_id,
                            stream,
                        )
            try:
                await db.commit()
            except Exception:
                logger.exception("db_event_dispatcher: commit failed for %s", stream)
                await db.rollback()
                continue

        if ack_ids:
            try:
                await redis.xack(stream, CONSUMER_GROUP, *ack_ids)
            except Exception:
                logger.exception("db_event_dispatcher: xack failed for %s", stream)

    return {"streams": len(streams), "events": total_events, "inserted": total_inserted}
