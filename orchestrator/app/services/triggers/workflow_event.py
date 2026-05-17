"""Workflow-event trigger adapter (G5, issue #469).

Fires the doctor (or any other automation that subscribes) when a
matching event lands in ``automation_run_events`` for a watched
workflow.

Trigger config shape::

    {
        "watched_automation_id": "<uuid>",
        "event_kinds": ["run.failed", "error.raised", "step.failed"]
    }

A small sweep (G5 follow-up) periodically scans the event log for
new matching rows since the last sweep and dispatches one
AutomationEvent per (subscribing_automation, source_event) pair.
For now the public hook is :func:`route_workflow_event` which the
event_log writer can call directly.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models_automations import AutomationDefinition, AutomationTrigger
from .common import dispatch_for_trigger

logger = logging.getLogger(__name__)


async def route_workflow_event(
    db: AsyncSession,
    *,
    source_automation_id: UUID,
    source_run_id: UUID | None,
    event_kind: str,
    payload: dict[str, Any] | None = None,
) -> list[UUID]:
    """Match an event from source_automation_id against workflow_event
    triggers. Returns the list of minted AutomationEvent ids.
    """
    # Push the watched_automation_id filter into the database via the
    # JSON ``->>`` operator so we only return triggers that actually
    # subscribe to this source. With the partial expression index added
    # in migration 0117 this turns a full table-scan per emit into a
    # cheap lookup. The cast keeps the comparison robust against
    # UUID/str representation drift in stored configs.
    source_id_str = str(source_automation_id)
    triggers = (
        await db.execute(
            select(AutomationTrigger, AutomationDefinition)
            .join(
                AutomationDefinition,
                AutomationDefinition.id == AutomationTrigger.automation_id,
            )
            .where(
                AutomationTrigger.kind == "workflow_event",
                AutomationTrigger.is_active.is_(True),
                AutomationDefinition.is_active.is_(True),
                # JSON ``->>`` returns text; works on both Postgres JSON
                # and JSONB. SQLite's JSON1 implements the same operator
                # so tests continue to pass.
                AutomationTrigger.config["watched_automation_id"].as_string() == source_id_str,
            )
        )
    ).all()

    matched: list[UUID] = []
    for trigger, definition in triggers:
        cfg = trigger.config or {}
        watched = cfg.get("watched_automation_id")
        if not watched or str(watched) != str(source_automation_id):
            continue
        kinds = cfg.get("event_kinds") or []
        if kinds and event_kind not in kinds:
            continue

        # Idempotency: source run + event kind = one fired event per
        # subscriber. Prevents the sweep / live writer from double-
        # firing the doctor.
        idem_seed = f"{definition.id}|{source_run_id or 'none'}|{event_kind}"
        idem = "workflow_event:" + hashlib.sha256(idem_seed.encode()).hexdigest()[:32]
        event_id = await dispatch_for_trigger(
            db,
            automation_id=definition.id,
            trigger_id=trigger.id,
            trigger_kind="workflow_event",
            payload={
                "source": "workflow_event",
                "source_automation_id": str(source_automation_id),
                "source_run_id": str(source_run_id) if source_run_id else None,
                "event_kind": event_kind,
                "event_payload": payload or {},
            },
            idempotency_key=idem,
        )
        matched.append(event_id)
        logger.info(
            "workflow_event.matched subscriber=%s source=%s kind=%s event=%s",
            definition.id,
            source_automation_id,
            event_kind,
            event_id,
        )

    return matched


# Silence unused-import warnings (uuid is reused in tests / future helpers).
_ = uuid
