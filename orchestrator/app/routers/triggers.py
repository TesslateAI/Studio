"""HTTP routers for inbound trigger sources (Phase E, issue #474).

Two endpoints, both under ``/api/triggers/inbound/`` so the CSRF
middleware's prefix exemption stays narrow and any future route
sibling (``/api/triggers/cancel``, ``/api/triggers/list``, …) gets
CSRF enforcement by default:

* ``POST /api/triggers/inbound/email`` — SES inbound notification
  receiver. Parses the SES envelope, calls
  :func:`services.triggers.email_inbound.route_inbound_email`, then
  dispatches each matched event synchronously so the response carries
  the run ids for replay debugging.
* ``POST /api/triggers/inbound/slack/{channel_config_id}`` —
  Slack-message trigger receiver. Used by the existing channel
  inbound when it also wants to fire workflow triggers.

Both endpoints REJECT unsigned traffic. The caller must:

* Provide ``X-Inbound-Timestamp`` (epoch seconds; rejected if
  older than ``get_settings().inbound_signature_max_age``).
* Provide ``X-Inbound-Signature`` formatted as ``sha256=<hex>`` where
  the HMAC is ``HMAC_SHA256(secret, f"v0:{ts}:{raw_body}")`` —
  the same scheme Slack uses. Slack's native
  ``X-Slack-Signature`` / ``X-Slack-Request-Timestamp`` headers are
  also accepted for the slack route so platform webhooks work
  out-of-the-box.

If the corresponding signing secret is not configured in settings,
the route returns 503 — explicit failure beats accidentally
accepting anonymous internet traffic on a misconfigured deploy.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.params import Depends as _Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models_automations import AutomationEvent
from ..services.automations.dispatcher import dispatch_automation
from ..services.triggers.email_inbound import route_inbound_email
from ..services.triggers.slack_message import route_inbound_message

# Use the standard FastAPI Depends alias; the import shape above keeps
# tooling that does not understand ``fastapi.params.Depends`` happy.
Depends = _Depends

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/triggers", tags=["triggers"])


# ---------------------------------------------------------------------------
# HMAC signature verification (#474 blocker #7)
# ---------------------------------------------------------------------------


def _hmac_sha256_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _consteq(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


async def _verify_inbound_signature(
    request: Request,
    *,
    secret: str,
    timestamp_header: str | None,
    signature_header: str | None,
) -> bytes:
    """Verify the request body against an HMAC signature.

    Raises HTTPException on any mismatch. Returns the raw body bytes
    so the route can JSON-decode them itself without reading the
    stream twice.
    """
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="inbound trigger signing secret not configured",
        )
    if not timestamp_header or not signature_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing inbound signature headers",
        )
    try:
        ts = int(timestamp_header)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid timestamp",
        ) from exc

    skew = abs(int(time.time()) - ts)
    if skew > get_settings().inbound_signature_max_age:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="timestamp outside replay window",
        )

    raw = await request.body()
    expected = "sha256=" + _hmac_sha256_hex(secret, f"v0:{ts}:".encode() + raw)
    # Slack's native header is ``v0=<hex>``; accept that shape too so a
    # raw Slack subscription POST works without an adapter.
    expected_slack = "v0=" + _hmac_sha256_hex(secret, f"v0:{ts}:".encode() + raw)
    if not (_consteq(signature_header, expected) or _consteq(signature_header, expected_slack)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="signature mismatch",
        )
    return raw


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


@router.post("/inbound/email", status_code=status.HTTP_202_ACCEPTED)
async def email_inbound(
    request: Request,
    x_inbound_timestamp: str | None = Header(default=None, alias="X-Inbound-Timestamp"),
    x_inbound_signature: str | None = Header(default=None, alias="X-Inbound-Signature"),
    db: AsyncSession = Depends(get_db),
):
    """Receive an inbound email envelope (SES-shaped).

    Required body fields: ``sender``, ``recipient``. Optional:
    ``subject``, ``body``, ``message_id``, ``raw``.

    Required headers: ``X-Inbound-Timestamp`` + ``X-Inbound-Signature``
    (``sha256=<hex>``) — HMAC computed against
    ``get_settings().inbound_email_signing_secret``.
    """
    import json

    raw_body = await _verify_inbound_signature(
        request,
        secret=get_settings().inbound_email_signing_secret,
        timestamp_header=x_inbound_timestamp,
        signature_header=x_inbound_signature,
    )
    try:
        payload = json.loads(raw_body or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc

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


@router.post("/inbound/slack/{channel_config_id}", status_code=status.HTTP_202_ACCEPTED)
async def slack_message_inbound(
    channel_config_id: UUID,
    request: Request,
    x_inbound_timestamp: str | None = Header(default=None, alias="X-Inbound-Timestamp"),
    x_inbound_signature: str | None = Header(default=None, alias="X-Inbound-Signature"),
    x_slack_request_timestamp: str | None = Header(default=None, alias="X-Slack-Request-Timestamp"),
    x_slack_signature: str | None = Header(default=None, alias="X-Slack-Signature"),
    db: AsyncSession = Depends(get_db),
):
    """Receive an inbound Slack message envelope.

    Required body fields: ``channel_id`` (or ``channel``).
    Optional: ``user_id``, ``body`` (or ``text``), ``raw``.

    Required headers: either ``X-Slack-Request-Timestamp`` +
    ``X-Slack-Signature`` (Slack's native scheme) OR our generic
    ``X-Inbound-Timestamp`` + ``X-Inbound-Signature`` — both verified
    against ``get_settings().inbound_slack_signing_secret``.
    """
    import json

    raw_body = await _verify_inbound_signature(
        request,
        secret=get_settings().inbound_slack_signing_secret,
        timestamp_header=x_slack_request_timestamp or x_inbound_timestamp,
        signature_header=x_slack_signature or x_inbound_signature,
    )
    try:
        payload = json.loads(raw_body or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc

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
