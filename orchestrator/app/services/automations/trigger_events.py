"""AutomationEvent ingest + state-transition helpers (Phase 1).

The webhook handler (``routers/app_triggers.py``) and the cron tick path
both create rows in ``automation_events`` and stamp them through a small
state machine:

    received_at  ──► dispatched_at   (success)
                  └► failed_at       (terminal failure to enqueue)

These helpers wrap the three transitions so the router stays readable and
the recovery sweep in ``services/apps/schedule_triggers.py`` shares a
single source of truth for column semantics.

Each helper performs **one statement**. Callers own the surrounding
transaction (commit/rollback). The webhook handler interleaves an
``ingest_trigger_event`` + ``mark_dispatched`` pair across two commits on
purpose: the event row must be durable before the ARQ enqueue so we have a
recovery target if the process crashes between INSERT and enqueue.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models_automations import AutomationEvent

__all__ = [
    "ingest_trigger_event",
    "mark_dispatched",
    "mark_failed",
    "mark_processed",
]

logger = logging.getLogger(__name__)


async def ingest_trigger_event(
    db: AsyncSession,
    *,
    automation_id: UUID,
    trigger_id: UUID | None,
    trigger_kind: str,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
) -> UUID:
    """Insert a fresh ``automation_events`` row.

    Returns the new event id. Caller must commit. ``idempotency_key`` is
    optional — when set, the partial unique index in alembic 0074 enforces
    one event per key; the IntegrityError must be handled by the caller
    (the webhook handler does not use this column in Phase 1).
    """
    event_id = uuid.uuid4()
    db.add(
        AutomationEvent(
            id=event_id,
            automation_id=automation_id,
            trigger_id=trigger_id,
            trigger_kind=trigger_kind,
            payload=payload or {},
            idempotency_key=idempotency_key,
        )
    )
    await db.flush()
    logger.debug(
        "automation_event.ingest event=%s automation=%s trigger=%s kind=%s",
        event_id,
        automation_id,
        trigger_id,
        trigger_kind,
    )
    return event_id


async def mark_dispatched(db: AsyncSession, event_id: UUID) -> None:
    """Stamp ``dispatched_at`` on a successfully-enqueued event."""
    await db.execute(
        update(AutomationEvent)
        .where(AutomationEvent.id == event_id)
        .values(dispatched_at=datetime.now(tz=UTC))
    )


async def mark_processed(db: AsyncSession, event_id: UUID) -> None:
    """Stamp ``processed_at`` after the run reaches a terminal state.

    The dispatcher calls this from the success path so the event row's
    state machine reflects ``received → dispatched → processed``. Recovery
    sweeps treat ``processed_at IS NOT NULL`` as the strongest "done"
    signal — the dispatched-but-not-processed window is the only spot a
    sweep needs to revisit.
    """
    await db.execute(
        update(AutomationEvent)
        .where(AutomationEvent.id == event_id)
        .values(processed_at=datetime.now(tz=UTC))
    )


async def mark_failed(db: AsyncSession, event_id: UUID, error: str) -> None:
    """Stamp ``failed_at`` + ``last_error`` on a permanently-failed event.

    ``error`` is truncated to 1000 characters to bound the column footprint
    and avoid leaking entire stack traces into the row.
    """
    await db.execute(
        update(AutomationEvent)
        .where(AutomationEvent.id == event_id)
        .values(
            failed_at=datetime.now(tz=UTC),
            last_error=(error or "")[:1000],
        )
    )
