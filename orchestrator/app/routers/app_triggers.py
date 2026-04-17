"""Public webhook trigger endpoint for app-instance schedules.

Authenticated via HMAC-SHA256 over the raw request body using a per-schedule
shared secret stored in :class:`AgentSchedule.trigger_config`.

Two storage shapes are supported:

* ``trigger_config["webhook_secrets"]`` — list of
  ``{kid, secret, created_at, revoked_at}`` entries. Rotation/revocation
  endpoints (``routers/app_schedules.py``) manage this list.
* ``trigger_config["webhook_secret"]`` — legacy single string. Read-only
  fallback so existing secrets keep verifying; new installs always write
  the list shape.

Callers MAY pin a specific kid via the ``x-tesslate-key-id`` header. If
absent, every non-revoked secret is tried (constant-time per attempt). The
match is recorded in the audit log; rejection is also audited so revoked /
leaked secrets become visible to the team.

Not subject to session auth or CSRF — callers are external systems.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import AgentSchedule, AppInstance, Project, ScheduleTriggerEvent
from ..services.audit_service import log_event

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


def _normalize_sig(provided: str) -> str:
    s = (provided or "").strip()
    if s.lower().startswith("sha256="):
        s = s.split("=", 1)[1]
    return s


def _hmac_hex(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _candidate_secrets(trig_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Return non-revoked secrets in the new list shape, falling back to the
    legacy single-key shape. Each entry is normalized to the dict form so the
    verifier can treat them uniformly.
    """
    raw_list = trig_cfg.get("webhook_secrets")
    out: list[dict[str, Any]] = []
    if isinstance(raw_list, list) and raw_list:
        for entry in raw_list:
            if not isinstance(entry, dict):
                continue
            secret = entry.get("secret")
            if not secret or entry.get("revoked_at"):
                continue
            out.append(
                {
                    "kid": entry.get("kid") or "v?",
                    "secret": str(secret),
                }
            )
        return out
    legacy = trig_cfg.get("webhook_secret")
    if isinstance(legacy, str) and legacy:
        out.append({"kid": "legacy", "secret": legacy})
    return out


async def _resolve_team_id(db: AsyncSession, sched: AgentSchedule) -> UUID | None:
    """Best-effort team_id lookup for audit logging from the webhook path."""
    project_id = sched.project_id
    if project_id is None and sched.app_instance_id is not None:
        inst = await db.get(AppInstance, sched.app_instance_id)
        if inst is not None:
            project_id = inst.project_id
    if project_id is None:
        return None
    project = await db.get(Project, project_id)
    return getattr(project, "team_id", None) if project is not None else None


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
    candidates = _candidate_secrets(trig_cfg)
    if not candidates:
        logger.error(
            "app_triggers: schedule %s has trigger_kind=webhook but no usable secrets",
            sched.id,
        )
        raise HTTPException(status_code=500, detail="webhook misconfigured")

    provided_sig = _normalize_sig(request.headers.get("x-tesslate-signature", ""))
    requested_kid = (request.headers.get("x-tesslate-key-id") or "").strip() or None

    matched_kid: str | None = None
    if requested_kid is not None:
        # Pinned-kid path: verify exactly one secret. Unknown / revoked kid
        # short-circuits to 401 without leaking which kids exist.
        target = next((c for c in candidates if c["kid"] == requested_kid), None)
        if target is not None:
            expected = _hmac_hex(target["secret"], body_bytes)
            if _timing_safe_eq(provided_sig, expected):
                matched_kid = target["kid"]
    else:
        # Fall-through: try each non-revoked secret. First match wins. Each
        # comparison is constant-time; the loop itself is not, but the kid
        # set is small (<=N rotations) and not attacker-controlled.
        for cand in candidates:
            expected = _hmac_hex(cand["secret"], body_bytes)
            if _timing_safe_eq(provided_sig, expected):
                matched_kid = cand["kid"]
                break

    if matched_kid is None:
        logger.warning(
            "app_triggers: HMAC mismatch instance=%s trigger=%s kid_hint=%s",
            instance_id,
            trigger_name,
            requested_kid,
        )
        # Audit signature rejection — best-effort, must not gate the 401.
        try:
            team_id = await _resolve_team_id(db, sched)
            if team_id is not None:
                await log_event(
                    db=db,
                    team_id=team_id,
                    user_id=sched.user_id,
                    action="webhook_signature_rejected",
                    resource_type="agent_schedule",
                    resource_id=sched.id,
                    project_id=sched.project_id,
                    details={
                        "instance_id": str(instance_id),
                        "trigger": trigger_name,
                        "requested_kid": requested_kid,
                    },
                    request=request,
                )
                await db.commit()
        except Exception:
            logger.exception("app_triggers: failed to audit rejection (non-blocking)")
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

    # Audit success alongside the event insert so they share the same commit.
    try:
        team_id = await _resolve_team_id(db, sched)
        if team_id is not None:
            await log_event(
                db=db,
                team_id=team_id,
                user_id=sched.user_id,
                action="webhook_triggered",
                resource_type="agent_schedule",
                resource_id=sched.id,
                project_id=sched.project_id,
                details={
                    "instance_id": str(instance_id),
                    "trigger": trigger_name,
                    "kid": matched_kid,
                    "event_id": str(event.id),
                },
                request=request,
            )
    except Exception:
        logger.exception("app_triggers: failed to audit success (non-blocking)")

    await db.commit()

    logger.info(
        "app_triggers.webhook_trigger instance=%s trigger=%s event=%s kid=%s",
        instance_id, trigger_name, event.id, matched_kid,
    )
    return TriggerAccepted(event_id=event.id, status="enqueued")
