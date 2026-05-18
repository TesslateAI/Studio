"""Slack-message trigger adapter (Phase E, issue #474).

Subscribes to inbound Slack messages routed by the existing channel
gateway and matches them against ``AutomationTrigger`` rows of kind
``slack_message``. On a match, mints an ``AutomationEvent`` and calls
``dispatch_automation`` so the workflow runs.

Trigger config shape (stored in ``AutomationTrigger.config`` as JSON)::

    {
        "channel_config_id": "<uuid>",  # required: which Slack workspace
        "channel_id": "C0123ABCDEF",    # optional: filter to one channel
        "regex": "^build status",       # optional: body regex (re.IGNORECASE)
        "user_mention": "U0PLATFORM"    # optional: only fire when this user is mentioned
    }

Phase E ships the matcher + dispatch path. The actual hook into the
existing inbound gateway (``services/channels/_inbound_dispatch.py``)
is a one-line addition the gateway owner wires in: after the
existing ``_inbound_dispatch`` returns, call
:func:`route_inbound_message` with the parsed envelope and a fresh
``AsyncSession``. We keep it pull-style (the gateway calls into us)
rather than push-style (us subscribing to a redis stream) so the
gateway's existing per-message lock and rate-limit logic still
applies.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models_automations import AutomationDefinition, AutomationTrigger
from .common import dispatch_for_trigger

logger = logging.getLogger(__name__)


async def route_inbound_message(
    db: AsyncSession,
    *,
    channel_config_id: uuid.UUID,
    channel_id: str,
    user_id: str | None,
    body: str,
    raw: dict[str, Any] | None = None,
) -> list[uuid.UUID]:
    """Match an inbound Slack message against active slack_message triggers.

    Returns the list of newly-minted ``AutomationEvent`` ids (one per
    matched trigger). The caller is responsible for invoking
    ``dispatch_automation`` against each event.

    Matching rules: a trigger fires when ALL of its non-null config
    filters match the inbound. A trigger with no filters fires for
    every message on the configured channel_config.
    """
    triggers = (
        await db.execute(
            select(AutomationTrigger, AutomationDefinition)
            .join(
                AutomationDefinition,
                AutomationDefinition.id == AutomationTrigger.automation_id,
            )
            .where(
                AutomationTrigger.kind == "slack_message",
                AutomationTrigger.is_active.is_(True),
                AutomationDefinition.is_active.is_(True),
            )
        )
    ).all()

    matched_event_ids: list[uuid.UUID] = []
    for trigger, definition in triggers:
        cfg = trigger.config or {}
        if not _matches(
            cfg,
            channel_config_id=channel_config_id,
            channel_id=channel_id,
            user_id=user_id,
            body=body,
        ):
            continue

        idem = _idempotency_key(
            automation_id=definition.id,
            channel_id=channel_id,
            body=body,
            user_id=user_id,
            event_id=(raw or {}).get("event_id"),
            ts=(raw or {}).get("ts") or (raw or {}).get("event_ts"),
        )
        event_id = await dispatch_for_trigger(
            db,
            automation_id=definition.id,
            trigger_id=trigger.id,
            trigger_kind="slack_message",
            payload={
                "source": "slack",
                "channel_id": channel_id,
                "user_id": user_id,
                "body": body[:8000],
                "raw": raw,
            },
            idempotency_key=idem,
        )
        matched_event_ids.append(event_id)
        logger.info(
            "slack_message.matched automation=%s trigger=%s event=%s",
            definition.id,
            trigger.id,
            event_id,
        )

    return matched_event_ids


def _matches(
    cfg: dict[str, Any],
    *,
    channel_config_id: uuid.UUID,
    channel_id: str,
    user_id: str | None,
    body: str,
) -> bool:
    cfg_cc = cfg.get("channel_config_id")
    if cfg_cc and str(cfg_cc) != str(channel_config_id):
        return False
    cfg_channel = cfg.get("channel_id")
    if cfg_channel and cfg_channel != channel_id:
        return False
    cfg_user = cfg.get("user_mention") or cfg.get("user_id")
    if cfg_user and cfg_user != user_id:
        return False
    cfg_regex = cfg.get("regex")
    if cfg_regex:
        try:
            if not re.search(cfg_regex, body, flags=re.IGNORECASE):
                return False
        except re.error:
            # Bad regex in config: log and treat as no-match so we
            # don't fire on every message indefinitely.
            logger.warning(
                "slack_message.bad_regex pattern=%r body_len=%d",
                cfg_regex,
                len(body),
            )
            return False
    return True


def _idempotency_key(
    *,
    automation_id: uuid.UUID,
    channel_id: str,
    body: str,
    user_id: str | None,
    event_id: str | None = None,
    ts: str | None = None,
) -> str:
    """Stable key so a Slack retry doesn't double-fire the workflow.

    Prefer Slack's own ``event_id`` / ``ts`` when available — those
    are the natural keys for "same delivery, retried" semantics and
    let a user legitimately re-type the exact same message without
    being silently dedupe'd. Falls back to a body-hash for callers
    (tests, the older inbound dispatcher) that don't pass them.
    """
    natural = event_id or ts
    if natural:
        seed = f"{automation_id}|{channel_id}|{natural}"
    else:
        seed = f"{automation_id}|{channel_id}|{user_id or ''}|{body}"
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return f"slack_message:{digest[:32]}"
