"""Email-inbound trigger adapter (Phase E, issue #474).

Receives inbound mail (parsed sender / recipient / subject / body) and
matches against ``AutomationTrigger`` rows of kind ``email_inbound``.
On a match, mints an ``AutomationEvent`` and lets the caller dispatch.

Trigger config shape::

    {
        "recipient": "robot@example.com",       # required: address to match
        "from_allowlist": ["alice@..."],        # optional: only fire from these senders
        "subject_regex": "^\\[deploy\\]"        # optional: subject filter (case-insensitive)
    }

Phase E supports SES inbound (preferred for AWS) — the SES inbound
notification posts a parsed JSON envelope to ``/api/triggers/email``
which calls into :func:`route_inbound_email`. IMAP poll is a Phase E
follow-up; same matching predicate, different transport.
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


async def route_inbound_email(
    db: AsyncSession,
    *,
    sender: str,
    recipient: str,
    subject: str,
    body: str,
    message_id: str | None = None,
    raw: dict[str, Any] | None = None,
) -> list[uuid.UUID]:
    """Match an inbound email against active email_inbound triggers.

    Returns event ids for each matched trigger. The caller invokes
    ``dispatch_automation`` per event.
    """
    triggers = (
        await db.execute(
            select(AutomationTrigger, AutomationDefinition)
            .join(
                AutomationDefinition,
                AutomationDefinition.id == AutomationTrigger.automation_id,
            )
            .where(
                AutomationTrigger.kind == "email_inbound",
                AutomationTrigger.is_active.is_(True),
                AutomationDefinition.is_active.is_(True),
            )
        )
    ).all()

    matched_event_ids: list[uuid.UUID] = []
    for trigger, definition in triggers:
        cfg = trigger.config or {}
        if not _matches(cfg, sender=sender, recipient=recipient, subject=subject):
            continue

        idem = _idempotency_key(
            automation_id=definition.id,
            message_id=message_id,
            sender=sender,
            subject=subject,
        )
        event_id = await dispatch_for_trigger(
            db,
            automation_id=definition.id,
            trigger_id=trigger.id,
            trigger_kind="email_inbound",
            payload={
                "source": "email",
                "sender": sender,
                "recipient": recipient,
                "subject": subject,
                "body": body[:8000],
                "message_id": message_id,
                "raw": raw,
            },
            idempotency_key=idem,
        )
        matched_event_ids.append(event_id)
        logger.info(
            "email_inbound.matched automation=%s trigger=%s event=%s",
            definition.id,
            trigger.id,
            event_id,
        )

    return matched_event_ids


def _matches(
    cfg: dict[str, Any],
    *,
    sender: str,
    recipient: str,
    subject: str,
) -> bool:
    cfg_recipient = cfg.get("recipient")
    if cfg_recipient and cfg_recipient.lower() != recipient.lower():
        return False
    allowlist = cfg.get("from_allowlist")
    if allowlist:
        sender_l = sender.lower()
        if not any(allowed.lower() == sender_l for allowed in allowlist):
            return False
    subject_re = cfg.get("subject_regex")
    if subject_re:
        try:
            if not re.search(subject_re, subject, flags=re.IGNORECASE):
                return False
        except re.error:
            logger.warning(
                "email_inbound.bad_regex pattern=%r subject_len=%d",
                subject_re,
                len(subject),
            )
            return False
    return True


def _idempotency_key(
    *,
    automation_id: uuid.UUID,
    message_id: str | None,
    sender: str,
    subject: str,
) -> str:
    """Stable key. RFC 5322 Message-ID is the natural key when present;
    fall back to a content hash so a forwarded retry without a
    Message-ID still dedupes against the dispatcher's idempotency
    window."""
    if message_id:
        return f"email_inbound:{message_id}"
    digest = hashlib.sha256(f"{automation_id}|{sender}|{subject}".encode()).hexdigest()
    return f"email_inbound:{digest[:32]}"
