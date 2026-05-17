"""HTTP routers for Phase E typed inbound trigger sources (issue #474).

Both endpoints live under ``/api/triggers/inbound/`` so the CSRF
middleware's prefix exemption stays narrow.

* ``POST /api/triggers/inbound/email`` — SES inbound notification.
  Required body: ``sender``, ``recipient`` (+ optional ``subject``,
  ``body``, ``message_id``, ``raw``).
* ``POST /api/triggers/inbound/slack/{channel_config_id}`` — inbound
  Slack envelope. Required body: ``channel_id`` (+ optional
  ``user_id``, ``body``/``text``, ``raw``).

These are **typed adapters** layered on top of the per-trigger HMAC
infrastructure that develop standardised in ``routers/app_triggers.py``
and the standalone-webhook auto-provisioner in
``routers/automations.py::_replace_triggers``:

1. Resolve the matching ``AutomationTrigger`` row by URL parameter
   (``channel_config_id`` for Slack; ``recipient`` matched against
   ``config["recipient"]`` for email).
2. Verify HMAC against ``trigger.config["webhook_secrets"][]`` using
   :func:`services.triggers.webhook_hmac.verify_webhook_signature`.
   Accepts the standard ``X-Tesslate-Signature: sha256=<hex>`` header
   AND Slack's native ``X-Slack-Signature: v0=<hex>`` so platform
   webhooks work without an adapter glue.
3. On verify, hand the typed body to our domain parsers
   (``route_inbound_email`` / ``route_inbound_message``) so workflow
   actions get a normalized event payload rather than a raw blob.

The deprecated global ``INBOUND_*_SIGNING_SECRET`` env vars are gone —
secrets now live per-trigger and rotate via ``webhook_secrets[]``.
"""

from __future__ import annotations

import json
import logging
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models_automations import AutomationDefinition, AutomationEvent, AutomationTrigger
from ..services.automations.dispatcher import dispatch_automation
from ..services.triggers.email_inbound import route_inbound_email
from ..services.triggers.slack_message import route_inbound_message
from ..services.triggers.webhook_hmac import (
    candidate_secrets,
    verify_webhook_signature,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/triggers", tags=["triggers"])


# ---------------------------------------------------------------------------
# Shared verifier (adapter on top of services.triggers.webhook_hmac)
# ---------------------------------------------------------------------------


_MAX_INBOUND_BODY_BYTES = 1_048_576  # 1 MiB — matches app_triggers cap


async def _read_capped_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            n = int(declared)
        except (TypeError, ValueError):
            n = -1
        if n > _MAX_INBOUND_BODY_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"payload exceeds {_MAX_INBOUND_BODY_BYTES} bytes",
            )
    body = await request.body()
    if len(body) > _MAX_INBOUND_BODY_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"payload exceeds {_MAX_INBOUND_BODY_BYTES} bytes",
        )
    return body


def _verify_typed_inbound(
    *,
    request: Request,
    body_bytes: bytes,
    trigger: AutomationTrigger,
) -> str:
    """Verify the request body against the trigger's
    ``config.webhook_secrets[]``. Returns the matched ``kid`` for
    audit. Raises typed HTTPException on any failure.

    Accepts both ``X-Tesslate-Signature`` (canonical) and Slack's
    native ``X-Slack-Signature`` so a Slack subscription works
    out-of-the-box.
    """
    trig_cfg = dict(trigger.config or {}) if isinstance(trigger.config, dict) else {}
    cands = candidate_secrets(trig_cfg)
    if not cands:
        # No secret ever provisioned — deployment bug, not caller error.
        raise HTTPException(
            status_code=503,
            detail="inbound trigger missing webhook_secrets (re-save the automation)",
        )

    provided = request.headers.get("x-tesslate-signature") or request.headers.get(
        "x-slack-signature"
    )
    kid_hint = (request.headers.get("x-tesslate-key-id") or "").strip() or None

    matched = verify_webhook_signature(
        body_bytes=body_bytes,
        provided_signature=provided,
        requested_kid=kid_hint,
        candidates=cands,
    )
    if matched is None:
        raise HTTPException(status_code=401, detail="invalid signature")
    return matched


# ---------------------------------------------------------------------------
# Dispatch helper
# ---------------------------------------------------------------------------


async def _dispatch_events(db: AsyncSession, event_ids: list[UUID]) -> list[str]:
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


# ---------------------------------------------------------------------------
# /inbound/email — adapter for SES SNS notifications + curl-shaped tests
# ---------------------------------------------------------------------------


async def _resolve_email_trigger(db: AsyncSession, *, recipient: str) -> AutomationTrigger | None:
    """Find an active email_inbound trigger whose ``config.recipient``
    matches the inbound envelope. Bounded read — small kind subset."""
    rows = (
        await db.execute(
            select(AutomationTrigger, AutomationDefinition)
            .join(
                AutomationDefinition,
                AutomationDefinition.id == AutomationTrigger.automation_id,
            )
            .where(
                AutomationTrigger.kind == "email_inbound",
                AutomationTrigger.is_active.is_(True),
            )
        )
    ).all()
    for trig, definition in rows:
        cfg = trig.config or {}
        if not isinstance(cfg, dict):
            continue
        cfg_recipient = cfg.get("recipient")
        if not isinstance(cfg_recipient, str):
            continue
        # Case-insensitive compare — email addresses are not case-sensitive
        # for the local-part in practice and SES normalises domains.
        if cfg_recipient.lower() == recipient.lower():
            _ = definition  # paused-check is the dispatcher's job
            return trig
    return None


@router.post("/inbound/email", status_code=status.HTTP_202_ACCEPTED)
async def email_inbound(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Receive an inbound email envelope (SES-shaped).

    Auth: HMAC-SHA256 of the raw body using one of the candidate
    secrets in the matched trigger's ``config.webhook_secrets[]``.
    The matching trigger row is found by ``recipient`` — the SES
    address whose local-part is the user's chosen alias.
    """
    raw_body = await _read_capped_body(request)
    try:
        payload = json.loads(raw_body or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc

    sender = payload.get("sender") or payload.get("from")
    recipient = payload.get("recipient") or payload.get("to")
    if not sender or not recipient:
        raise HTTPException(status_code=400, detail="sender and recipient are required")

    trigger = await _resolve_email_trigger(db, recipient=str(recipient))
    if trigger is None:
        # Don't act as a recipient-existence oracle for external callers.
        raise HTTPException(status_code=404, detail="trigger not found")

    matched_kid = _verify_typed_inbound(request=request, body_bytes=raw_body, trigger=trigger)
    logger.info(
        "email_inbound.verified trigger=%s kid=%s recipient=%s",
        trigger.id,
        matched_kid,
        recipient,
    )

    subject = payload.get("subject") or ""
    text_body = payload.get("body") or payload.get("text") or ""
    message_id = payload.get("message_id") or payload.get("messageId")
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


# ---------------------------------------------------------------------------
# /inbound/slack/{channel_config_id} — adapter for Slack event subscription
# ---------------------------------------------------------------------------


async def _resolve_slack_trigger(
    db: AsyncSession, *, channel_config_id: UUID
) -> AutomationTrigger | None:
    """Find an active slack_message trigger whose ``config
    .channel_config_id`` matches the URL parameter."""
    rows = (
        await db.execute(
            select(AutomationTrigger, AutomationDefinition)
            .join(
                AutomationDefinition,
                AutomationDefinition.id == AutomationTrigger.automation_id,
            )
            .where(
                AutomationTrigger.kind == "slack_message",
                AutomationTrigger.is_active.is_(True),
            )
        )
    ).all()
    cc_id_str = str(channel_config_id)
    for trig, definition in rows:
        cfg = trig.config or {}
        if not isinstance(cfg, dict):
            continue
        if str(cfg.get("channel_config_id") or "") == cc_id_str:
            _ = definition
            return trig
    return None


@router.post("/inbound/slack/{channel_config_id}", status_code=status.HTTP_202_ACCEPTED)
async def slack_message_inbound(
    channel_config_id: UUID,
    request: Request,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Receive an inbound Slack envelope.

    Auth: HMAC-SHA256 of the raw body. Slack's native
    ``X-Slack-Signature: v0=<hex>`` is accepted; the canonical
    ``X-Tesslate-Signature: sha256=<hex>`` works too. Matching
    trigger is found by ``channel_config_id`` from the URL.
    """
    raw_body = await _read_capped_body(request)
    # Re-parse from raw to keep HMAC body and decoded shape in sync; the
    # FastAPI Body(...) parameter is here for OpenAPI docs only.
    _ = payload  # type: ignore[unused-ignore]
    try:
        payload = json.loads(raw_body or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc

    channel_id = payload.get("channel_id") or payload.get("channel")
    if not channel_id:
        raise HTTPException(status_code=400, detail="channel_id (or channel) is required")

    trigger = await _resolve_slack_trigger(db, channel_config_id=channel_config_id)
    if trigger is None:
        raise HTTPException(status_code=404, detail="trigger not found")

    matched_kid = _verify_typed_inbound(request=request, body_bytes=raw_body, trigger=trigger)
    logger.info(
        "slack_inbound.verified trigger=%s kid=%s channel=%s",
        trigger.id,
        matched_kid,
        channel_id,
    )

    user_id = payload.get("user_id") or payload.get("user")
    body = payload.get("body") or payload.get("text") or ""
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
