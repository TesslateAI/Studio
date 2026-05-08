"""HTTP routers for inbound trigger sources (Phase E, issue #474).

Two endpoints:

* ``POST /api/triggers/email`` — SES inbound notification receiver.
  Parses the SES envelope, calls
  :func:`services.triggers.email_inbound.route_inbound_email`, then
  dispatches each matched event synchronously so the response carries
  the run ids for replay debugging.
* ``POST /api/triggers/slack/{channel_config_id}`` — Slack-message
  trigger receiver. Used by the existing channel inbound when it
  also wants to fire workflow triggers. A Phase F follow-up folds
  this back into the gateway path so callers don't have to fire
  twice.

Both endpoints accept arbitrary JSON and let the dispatcher's
idempotency key collapse retries safely.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models_automations import AutomationEvent
from ..services.automations.dispatcher import dispatch_automation
from ..services.triggers.email_inbound import route_inbound_email
from ..services.triggers.slack_message import route_inbound_message

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/triggers", tags=["triggers"])


async def _dispatch_events(db: AsyncSession, event_ids: list[UUID]) -> list[str]:
    """Look up each event by id and dispatch its automation. Returns run ids."""
    run_ids: list[str] = []
    for event_id in event_ids:
        evt = (
            await db.execute(select(AutomationEvent).where(AutomationEvent.id == event_id))
        ).scalar_one()
        result = await dispatch_automation(
            db,
            automation_id=evt.automation_id,
            event_id=event_id,
        )
        if result.run_id is not None:
            run_ids.append(str(result.run_id))
    return run_ids


@router.post("/email", status_code=status.HTTP_202_ACCEPTED)
async def email_inbound(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Receive an inbound email envelope (SES-shaped).

    Required body fields: ``sender``, ``recipient``. Optional:
    ``subject``, ``body``, ``message_id``, ``raw``. The SES SNS
    subscription parses the real envelope before posting here; this
    endpoint also accepts the same shape for tests via curl.
    """
    sender = payload.get("sender") or payload.get("from")
    recipient = payload.get("recipient") or payload.get("to")
    subject = payload.get("subject") or ""
    text_body = payload.get("body") or payload.get("text") or ""
    message_id = payload.get("message_id") or payload.get("messageId")
    if not sender or not recipient:
        raise HTTPException(status_code=400, detail="sender and recipient are required")

    event_ids = await route_inbound_email(
        db,
        sender=sender,
        recipient=recipient,
        subject=subject,
        body=text_body,
        message_id=message_id,
        raw=payload.get("raw"),
    )
    run_ids = await _dispatch_events(db, event_ids)
    return {
        "matched_triggers": len(event_ids),
        "event_ids": [str(e) for e in event_ids],
        "run_ids": run_ids,
    }


@router.post("/slack/{channel_config_id}", status_code=status.HTTP_202_ACCEPTED)
async def slack_message_inbound(
    channel_config_id: UUID,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Receive an inbound Slack message envelope.

    Required body fields: ``channel_id`` (or ``channel``).
    Optional: ``user_id``, ``body`` (or ``text``), ``raw``.
    """
    channel_id = payload.get("channel_id") or payload.get("channel")
    user_id = payload.get("user_id") or payload.get("user")
    body = payload.get("body") or payload.get("text") or ""
    if not channel_id:
        raise HTTPException(status_code=400, detail="channel_id (or channel) is required")

    event_ids = await route_inbound_message(
        db,
        channel_config_id=channel_config_id,
        channel_id=channel_id,
        user_id=user_id,
        body=body,
        raw=payload.get("raw"),
    )
    run_ids = await _dispatch_events(db, event_ids)
    return {
        "matched_triggers": len(event_ids),
        "event_ids": [str(e) for e in event_ids],
        "run_ids": run_ids,
    }
