"""Public webhook trigger endpoint for automations (Phase 1, enqueue-only).

The handler is the **fast path** of the Automation Runtime trigger pipeline:
it verifies the HMAC, INSERTs an ``automation_events`` row, enqueues a
single ARQ ``dispatch_automation_task`` job, and returns 202 — typically in
single-digit milliseconds. **All heavy work** (contract resolve, parent-
budget check, run idempotency upsert, action routing) runs inside the
worker (``services/automations/dispatcher.py::dispatch_automation``).

Why the rewrite
~~~~~~~~~~~~~~~

Pre-Phase-1 the handler called ``process_trigger_events_batch`` synchronously
inside the request — which holds the FastAPI worker, a DB connection, and a
Redis connection for *seconds* per call. Under burst (Slack incident
fan-out, app-event storms) FastAPI pool exhaustion was bounded by DB query
depth, not by ARQ enqueue throughput. The new shape decouples them: handler
holds resources for ~ms, ARQ absorbs the burst.

External contract (unchanged)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* URL  ``POST /api/app-instances/{instance_id}/trigger/{trigger_name}``
* Auth ``X-Tesslate-Signature: sha256=<hmac>`` over the raw request body,
  optional ``X-Tesslate-Key-Id`` to pin a specific kid.
* Body Arbitrary JSON (or raw bytes); stored under ``payload``.
* Response ``202`` with ``{"event_id", "trigger_event_id", "status"}``.

Two storage shapes for secrets are accepted (matching the legacy router):

* ``trigger.config["webhook_secrets"]`` — list of
  ``{kid, secret, created_at, revoked_at}`` entries (rotation-friendly).
* ``trigger.config["webhook_secret"]`` — legacy single string fallback.

Resolution
~~~~~~~~~~

The path's ``instance_id`` and ``trigger_name`` are looked up via
``AutomationTrigger`` rows whose ``kind='webhook'`` and whose JSON
``config`` carries ``app_instance_id == :instance_id`` and
``name == :trigger_name``. The associated ``AutomationDefinition`` must be
``is_active``. Missing definition or trigger → ``404``. Invalid signature
→ ``401``. Misconfigured trigger (no usable secrets) → ``500``.

Recovery
~~~~~~~~

A row that is INSERTed but never reaches ``mark_dispatched`` (handler crash
between commits) is picked up by the recovery sweep in
``services/apps/schedule_triggers.py::process_trigger_events_batch`` once
``received_at < now() - interval '5 seconds'``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Project
from ..models_automations import (
    AppInstance,
    AutomationDefinition,
    AutomationTrigger,
)
from ..services.audit_service import log_event
from ..services.automations.trigger_events import (
    ingest_trigger_event,
    mark_dispatched,
    mark_failed,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Response shape — preserves the legacy ``event_id`` field for existing
# callers, exposes the new ``trigger_event_id`` alias used by Phase 1+
# clients. ``status`` is always ``"enqueued"`` on success (the run isn't
# materialized yet — that happens in the worker).
# ---------------------------------------------------------------------------


class TriggerAccepted(BaseModel):
    event_id: UUID
    trigger_event_id: UUID
    status: str


# ---------------------------------------------------------------------------
# Signature verification helpers — identical algorithm to the legacy router.
# ---------------------------------------------------------------------------


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
    """Return non-revoked secrets in the new list shape, falling back to
    the legacy single-key shape. Each entry is normalized to the dict form
    so the verifier can treat them uniformly.
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
            out.append({"kid": entry.get("kid") or "v?", "secret": str(secret)})
        return out
    legacy = trig_cfg.get("webhook_secret")
    if isinstance(legacy, str) and legacy:
        out.append({"kid": "legacy", "secret": legacy})
    return out


def _verify_webhook_signature(
    *,
    request: Request,
    body_bytes: bytes,
    candidates: list[dict[str, Any]],
) -> str | None:
    """Return matched ``kid`` or ``None`` if no candidate verified.

    Pinned-kid path verifies exactly one secret. Fall-through tries each
    non-revoked secret in declaration order; first match wins. Each
    comparison is constant-time. The loop itself is not, but the kid set is
    small (<=N rotations) and not attacker-controlled.
    """
    provided_sig = _normalize_sig(request.headers.get("x-tesslate-signature", ""))
    requested_kid = (request.headers.get("x-tesslate-key-id") or "").strip() or None

    if requested_kid is not None:
        target = next((c for c in candidates if c["kid"] == requested_kid), None)
        if target is None:
            return None
        expected = _hmac_hex(target["secret"], body_bytes)
        return target["kid"] if _timing_safe_eq(provided_sig, expected) else None

    for cand in candidates:
        expected = _hmac_hex(cand["secret"], body_bytes)
        if _timing_safe_eq(provided_sig, expected):
            return cand["kid"]
    return None


# ---------------------------------------------------------------------------
# AutomationTrigger lookup — JSON-config keyed off the URL path.
#
# We cannot push the ``config->>'app_instance_id'`` predicate into the DB
# portably (Postgres has the ``->>`` operator; SQLite doesn't) so the
# handler does a narrow ``kind='webhook'`` SELECT joined to the active
# definition and filters in Python. The result set is bounded by the
# number of webhook triggers per definition (typically <5) and is hot-cache
# friendly — this is two indexed reads, not a scan.
# ---------------------------------------------------------------------------


async def _resolve_automation_for_webhook(
    db: AsyncSession,
    *,
    instance_id: UUID,
    trigger_name: str,
) -> tuple[AutomationDefinition | None, AutomationTrigger | None]:
    """Find the active AutomationDefinition + webhook AutomationTrigger
    bound to ``instance_id`` + ``trigger_name``.

    Returns ``(None, None)`` if no match (handler maps to 404). Both halves
    are returned so the caller can persist ``trigger_id`` on the event row.
    """
    stmt = (
        select(AutomationTrigger, AutomationDefinition)
        .join(
            AutomationDefinition,
            AutomationDefinition.id == AutomationTrigger.automation_id,
        )
        .where(AutomationTrigger.kind == "webhook")
        .where(AutomationTrigger.is_active.is_(True))
        .where(AutomationDefinition.is_active.is_(True))
    )
    rows = (await db.execute(stmt)).all()
    instance_id_str = str(instance_id)
    for trigger, automation in rows:
        cfg = trigger.config or {}
        if not isinstance(cfg, dict):
            continue
        cfg_instance = cfg.get("app_instance_id")
        cfg_name = cfg.get("name") or cfg.get("trigger_name")
        if str(cfg_instance) != instance_id_str:
            continue
        if cfg_name and str(cfg_name) != trigger_name:
            continue
        return automation, trigger
    return None, None


async def _resolve_team_id(
    db: AsyncSession,
    *,
    automation: AutomationDefinition,
    instance_id: UUID,
) -> UUID | None:
    """Best-effort team lookup for audit logging — never raises."""
    if automation.team_id is not None:
        return automation.team_id
    inst = await db.get(AppInstance, instance_id)
    if inst is None:
        return None
    project_id = getattr(inst, "project_id", None)
    if project_id is None:
        return None
    project = await db.get(Project, project_id)
    return getattr(project, "team_id", None) if project is not None else None


# ---------------------------------------------------------------------------
# ARQ pool — module-singleton pattern matching routers/chat.py and
# routers/channels.py (the rest of the codebase). Lazily created; a missing
# pool is a 500 because the dispatch path requires the queue to function.
# Override via ``app.dependency_overrides[get_arq_pool]`` in tests.
# ---------------------------------------------------------------------------


_arq_pool: Any = None


async def _create_arq_pool() -> Any:
    """Build an ARQ Redis pool from the orchestrator's redis URL."""
    from urllib.parse import urlparse

    from arq import create_pool
    from arq.connections import RedisSettings

    from ..config import get_settings

    settings = get_settings()
    redis_url = getattr(settings, "redis_url", "") or ""
    if not redis_url:
        return None
    parsed = urlparse(redis_url)
    return await create_pool(
        RedisSettings(
            host=parsed.hostname or "redis",
            port=parsed.port or 6379,
            database=int((parsed.path or "/0").lstrip("/") or "0"),
            password=parsed.password,
        )
    )


async def get_arq_pool() -> Any:
    """FastAPI dependency: return a cached ARQ pool, creating on first use."""
    global _arq_pool
    if _arq_pool is not None:
        return _arq_pool
    try:
        _arq_pool = await _create_arq_pool()
    except Exception:
        logger.exception("app_triggers: failed to create ARQ pool")
        _arq_pool = None
    return _arq_pool


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


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
    pool: Any = Depends(get_arq_pool),
) -> TriggerAccepted:
    body_bytes = await request.body()

    # Step 1 — find the AutomationTrigger + active AutomationDefinition.
    automation, trigger = await _resolve_automation_for_webhook(
        db, instance_id=instance_id, trigger_name=trigger_name
    )
    if automation is None or trigger is None:
        raise HTTPException(status_code=404, detail="trigger not found")

    # Step 2 — verify HMAC. Misconfigured triggers (no secrets) are 500
    # because the deployment is wrong; clients don't get to retry around it.
    trig_cfg = dict(trigger.config or {})
    candidates = _candidate_secrets(trig_cfg)
    if not candidates:
        logger.error(
            "app_triggers: trigger %s on automation %s has no usable secrets",
            trigger.id,
            automation.id,
        )
        raise HTTPException(status_code=500, detail="webhook misconfigured")

    matched_kid = _verify_webhook_signature(
        request=request, body_bytes=body_bytes, candidates=candidates
    )
    if matched_kid is None:
        logger.warning(
            "app_triggers: HMAC mismatch instance=%s trigger=%s",
            instance_id,
            trigger_name,
        )
        # Audit signature rejection — best-effort, must never gate the 401.
        try:
            team_id = await _resolve_team_id(
                db, automation=automation, instance_id=instance_id
            )
            if team_id is not None:
                await log_event(
                    db=db,
                    team_id=team_id,
                    user_id=automation.owner_user_id,
                    action="webhook_signature_rejected",
                    resource_type="automation_trigger",
                    resource_id=trigger.id,
                    project_id=automation.target_project_id,
                    details={
                        "instance_id": str(instance_id),
                        "trigger": trigger_name,
                    },
                    request=request,
                )
                await db.commit()
        except Exception:
            logger.exception("app_triggers: failed to audit rejection (non-blocking)")
        raise HTTPException(status_code=401, detail="invalid signature")

    # Step 3 — parse the body as JSON; fall back to raw text under ``_raw``
    # so the agent has *something* to inspect even for non-JSON callers.
    try:
        parsed = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except Exception:
        parsed = {"_raw": body_bytes.decode("utf-8", errors="replace")[:8192]}
    payload = parsed if isinstance(parsed, dict) else {"_payload": parsed}

    # Step 4 — single INSERT. Commit immediately so the row is durable
    # before we touch ARQ; recovery sweep keys off this.
    event_id = await ingest_trigger_event(
        db,
        automation_id=automation.id,
        trigger_id=trigger.id,
        trigger_kind="webhook",
        payload=payload,
    )
    await db.commit()

    # Step 5 — enqueue + mark dispatched. ARQ ``_job_id`` collapses
    # concurrent in-flight enqueues for the same event; the dispatcher's
    # idempotency upsert is the long-term safety net.
    if pool is None:
        await mark_failed(db, event_id, "no arq pool available")
        await db.commit()
        raise HTTPException(status_code=500, detail="task queue unavailable")

    client_host = request.client.host if request.client else "unknown"
    worker_id = f"webhook-handler:{client_host}"
    try:
        await pool.enqueue_job(
            "dispatch_automation_task",
            str(automation.id),
            str(event_id),
            worker_id,
            _job_id=str(event_id),
        )
    except Exception as exc:
        logger.exception(
            "app_triggers: failed to enqueue dispatch event=%s automation=%s",
            event_id,
            automation.id,
        )
        await mark_failed(db, event_id, repr(exc))
        await db.commit()
        raise HTTPException(status_code=500, detail="failed to enqueue dispatch") from exc

    await mark_dispatched(db, event_id)

    # Step 6 — audit success in the same TXN as the dispatched stamp.
    try:
        team_id = await _resolve_team_id(
            db, automation=automation, instance_id=instance_id
        )
        if team_id is not None:
            await log_event(
                db=db,
                team_id=team_id,
                user_id=automation.owner_user_id,
                action="webhook_triggered",
                resource_type="automation_trigger",
                resource_id=trigger.id,
                project_id=automation.target_project_id,
                details={
                    "instance_id": str(instance_id),
                    "trigger": trigger_name,
                    "kid": matched_kid,
                    "event_id": str(event_id),
                    "automation_id": str(automation.id),
                },
                request=request,
            )
    except Exception:
        logger.exception("app_triggers: failed to audit success (non-blocking)")

    await db.commit()

    logger.info(
        "app_triggers.webhook_trigger instance=%s trigger=%s event=%s automation=%s kid=%s",
        instance_id,
        trigger_name,
        event_id,
        automation.id,
        matched_kid,
    )
    return TriggerAccepted(
        event_id=event_id, trigger_event_id=event_id, status="enqueued"
    )
