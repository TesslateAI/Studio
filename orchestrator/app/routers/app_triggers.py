"""Public webhook trigger endpoint for app-instance schedules.

Authenticated via HMAC-SHA256 over the raw request body using the
``webhook_secret`` stored in the bound :class:`AgentSchedule.trigger_config`.
Not subject to session auth or CSRF — callers are external systems.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import AgentSchedule, ScheduleTriggerEvent

logger = logging.getLogger(__name__)
router = APIRouter()


class TriggerAccepted(BaseModel):
    event_id: UUID
    status: str


def _timing_safe_eq(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
    except Exception:
        return False


@router.post(
    "/api/app-instances/{instance_id}/trigger/{trigger_name}",
    response_model=TriggerAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["apps:triggers"],
)
async def webhook_trigger(
    instance_id: UUID,
    trigger_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TriggerAccepted:
    body_bytes = await request.body()

    sched = (
        await db.execute(
            select(AgentSchedule).where(
                AgentSchedule.app_instance_id == instance_id,
                AgentSchedule.name == trigger_name,
                AgentSchedule.trigger_kind == "webhook",
            )
        )
    ).scalar_one_or_none()
    if sched is None:
        raise HTTPException(status_code=404, detail="trigger not found")

    trig_cfg = dict(sched.trigger_config or {})
    secret = trig_cfg.get("webhook_secret")
    if not secret:
        logger.error(
            "app_triggers: schedule %s has trigger_kind=webhook but no webhook_secret",
            sched.id,
        )
        raise HTTPException(status_code=500, detail="webhook misconfigured")

    provided_sig = request.headers.get("x-tesslate-signature", "")
    expected = hmac.new(
        secret.encode("utf-8"), body_bytes, hashlib.sha256
    ).hexdigest()

    # Accept both raw hex and "sha256=<hex>" encodings.
    normalized = provided_sig.strip()
    if normalized.lower().startswith("sha256="):
        normalized = normalized.split("=", 1)[1]
    if not _timing_safe_eq(normalized, expected):
        logger.warning(
            "app_triggers: HMAC mismatch instance=%s trigger=%s", instance_id, trigger_name
        )
        raise HTTPException(status_code=401, detail="invalid signature")

    # Body can be arbitrary JSON; store as-is under payload.
    import json as _json

    try:
        payload = _json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except Exception:
        payload = {"_raw": body_bytes.decode("utf-8", errors="replace")[:8192]}

    event = ScheduleTriggerEvent(
        id=uuid.uuid4(),
        schedule_id=sched.id,
        payload=payload if isinstance(payload, dict) else {"_payload": payload},
        received_at=datetime.now(tz=timezone.utc),
    )
    db.add(event)
    await db.commit()

    logger.info(
        "app_triggers.webhook_trigger instance=%s trigger=%s event=%s",
        instance_id, trigger_name, event.id,
    )
    return TriggerAccepted(event_id=event.id, status="enqueued")
