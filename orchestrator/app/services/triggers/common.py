"""Shared helpers for trigger adapters.

The adapter pattern: each trigger source resolves an inbound event to
zero or more matching ``AutomationTrigger`` rows, persists an
``AutomationEvent`` per match, and calls
``dispatch_automation(automation_id, event_id)``. Idempotency is via
``AutomationEvent.idempotency_key`` (uniquely indexed when set); the
adapter computes a stable key from the source event so retries
collapse safely.

The adapter does NOT decide trigger config matching by itself in this
helper: each ``services/triggers/<source>.py`` owns the matching
predicate and feeds the resolved (automation_id, payload, idem_key)
tuples to :func:`dispatch_for_trigger`.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models_automations import AutomationEvent

logger = logging.getLogger(__name__)


async def dispatch_for_trigger(
    db: AsyncSession,
    *,
    automation_id: uuid.UUID,
    trigger_id: uuid.UUID | None,
    trigger_kind: str,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
) -> uuid.UUID:
    """Persist the AutomationEvent for one matched trigger and return its id.

    Phase E intentionally does NOT call ``dispatch_automation`` from here.
    The caller (the trigger router) handles that so it can return the
    HTTP response synchronously when the user expects one (Slack
    webhook timeout window) or hand off async (SES inbound, where
    delivery is already deferred).

    Idempotency: if ``idempotency_key`` is set and a row with that key
    already exists, return its id without inserting a duplicate. The
    unique partial index on ``automation_events.idempotency_key`` is
    the database-level guarantee.
    """
    if idempotency_key:
        from sqlalchemy import select

        existing = (
            await db.execute(
                select(AutomationEvent).where(
                    AutomationEvent.automation_id == automation_id,
                    AutomationEvent.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            logger.info(
                "trigger.dedupe automation=%s key=%s existing_event=%s",
                automation_id,
                idempotency_key,
                existing.id,
            )
            return existing.id

    evt = AutomationEvent(
        id=uuid.uuid4(),
        automation_id=automation_id,
        trigger_id=trigger_id,
        payload=payload or {},
        trigger_kind=trigger_kind,
        idempotency_key=idempotency_key,
    )
    db.add(evt)
    await db.commit()
    return evt.id
