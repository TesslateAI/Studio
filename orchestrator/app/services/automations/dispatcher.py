"""Automation dispatcher (Phase 1).

The dispatcher is the heavy worker that takes an :class:`AutomationEvent`
(created by webhook handler, cron tick, manual run, or app-event) and turns
it into an :class:`AutomationRun` that either succeeds, fails, pauses for
approval, or is cancelled.

Phase 1 ships a SINGLE-JOB dispatcher: ``dispatch_automation`` runs the
entire flow inside one ARQ task. The three-job split (dispatch -> provision
-> execute) lands in Phase 4 with the controller. Phase 1 is fine for now
since Tier 1 ephemeral pods cold-start fast and we don't need horizontal
backpressure yet -- but we DO stamp ``worker_id`` + ``heartbeat_at`` so the
Phase 4 sweep has the data it needs from day one.

What this module owns
---------------------
* **Idempotency at the run** -- the two-query INSERT/SELECT pattern from the
  plan. One ``(automation_id, event_id)`` pair always collapses to one
  ``automation_runs`` row regardless of how many times the dispatcher is
  invoked. The branch table on existing-run status decides whether to
  re-execute, retry, or no-op.
* **Contract preflight** -- the contract is REQUIRED on every automation
  (no NULL semantics under hard reset). Phase 1 only validates that the
  contract exists and is well-formed; minting LiteLLM keys + grant
  resolution land in Phase 2.
* **Action routing** -- branch on ``action_type`` to the right executor
  (``agent.run`` enqueues ``execute_agent_task``; ``app.invoke`` calls
  the apps action dispatcher; ``gateway.send`` XADDs to the gateway
  delivery stream via the typed envelope).
* **Heartbeat** -- writes ``worker_id`` + ``heartbeat_at`` so the Phase 4
  controller leader can sweep stale runs.

What this module deliberately does NOT do
-----------------------------------------
* No LiteLLM key minting (Phase 2 ``budget.py`` owns that).
* No grant resolution (Phase 2 ``grant_resolver.py`` owns that).
* No backpressure capacity check (Phase 2 ``approval_pressure.py`` owns
  that).
* No three-job split (Phase 4 controller owns that).
* No checkpoint serialization (Phase 2 ``checkpoint.py`` owns that).

Wave coordination notes
-----------------------
This module is built in parallel with Wave 2B (the real
``services/apps/action_dispatcher.py``). For ``app.invoke`` actions we call
through a small in-module stub that defers to the real implementation when
present and raises :class:`NotImplementedError` otherwise. The synthesis
step swaps the stub for the real wiring without touching the dispatcher
itself.
"""

from __future__ import annotations

import logging
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...models_automations import (
    AutomationAction,
    AutomationDefinition,
    AutomationDeliveryTarget,
    AutomationRun,
    AutomationRunArtifact,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class DispatchStatus(str, Enum):
    """Terminal classification of a single ``dispatch_automation`` call.

    Distinct from :class:`AutomationRun.status` -- this describes what the
    *call* did, not the run's lifecycle. ``retried_existing`` means we hit
    the idempotency upsert and the prior run was non-terminal; the caller
    should treat this as "nothing new happened, see the existing run".
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PAUSED = "paused"
    RETRIED_EXISTING = "retried_existing"
    NOOP_TERMINAL = "noop_terminal"
    NOOP_INFLIGHT = "noop_inflight"


@dataclass(frozen=True)
class DispatchResult:
    """Outcome of one ``dispatch_automation`` invocation.

    ``status`` is a :class:`DispatchStatus`; ``run_id`` is the
    :class:`AutomationRun.id` (always set -- we always have a run row by the
    time we return). ``run_status`` mirrors the run's terminal status so
    callers (routers, the Phase 4 controller, tests) don't have to re-read
    the row. ``reason`` carries the human-readable explanation when
    ``status`` is ``FAILED``/``PAUSED``/``NOOP_*``.
    """

    status: DispatchStatus
    run_id: UUID
    run_status: str
    reason: str | None = None


# ---------------------------------------------------------------------------
# Exception taxonomy
# ---------------------------------------------------------------------------


class DispatcherError(Exception):
    """Base class for dispatcher domain errors. Always carries a reason."""


class AutomationDefinitionMissing(DispatcherError):
    """The automation_definitions row is gone or has is_active=False."""


class ContractInvalid(DispatcherError):
    """The contract JSONB is missing required keys or malformed."""


class ActionDispatchFailed(DispatcherError):
    """An action executor raised. The wrapped error is in ``__cause__``."""


# ---------------------------------------------------------------------------
# Contract preflight
# ---------------------------------------------------------------------------

# Required keys on every contract. The Automation Builder defaults a
# project-derived template so users only edit deltas; the dispatcher
# enforces the schema as the last line of defense.
_REQUIRED_CONTRACT_KEYS = (
    "allowed_tools",
    "max_compute_tier",
)

_VALID_ON_BREACH = ("pause_for_approval", "hard_stop", "extend_once")


def _validate_contract(contract: Any) -> None:
    """Raise :class:`ContractInvalid` if the contract JSONB is malformed.

    Phase 1 only enforces structural validity. Phase 2's ContractGate
    layers semantics (allow-list checks, tier mapping, spend estimation)
    on top of the same dict.
    """
    if not isinstance(contract, dict):
        raise ContractInvalid(
            f"contract must be a JSON object, got {type(contract).__name__}"
        )

    missing = [k for k in _REQUIRED_CONTRACT_KEYS if k not in contract]
    if missing:
        raise ContractInvalid(f"contract missing required keys: {missing!r}")

    allowed_tools = contract.get("allowed_tools")
    # ``None`` means "inherit project defaults"; a list is the explicit form.
    if allowed_tools is not None and not isinstance(allowed_tools, list):
        raise ContractInvalid(
            "contract.allowed_tools must be null or a list of tool names"
        )

    tier = contract.get("max_compute_tier")
    if not isinstance(tier, int) or tier < 0:
        raise ContractInvalid(
            "contract.max_compute_tier must be a non-negative integer"
        )

    on_breach = contract.get("on_breach", "pause_for_approval")
    if on_breach not in _VALID_ON_BREACH:
        raise ContractInvalid(
            f"contract.on_breach={on_breach!r} not in {_VALID_ON_BREACH!r}"
        )


# ---------------------------------------------------------------------------
# Idempotency upsert (the two-query pattern from the plan)
# ---------------------------------------------------------------------------


async def _upsert_run(
    db: AsyncSession,
    *,
    automation_id: UUID,
    event_id: UUID,
    worker_id: str,
) -> tuple[AutomationRun, bool]:
    """Insert a fresh ``automation_runs`` row or return the existing one.

    Returns ``(run, inserted)``. If ``inserted`` is True this call won the
    race; the caller proceeds with the full flow. If False, the caller
    consults the existing run's ``status`` to decide whether to re-execute,
    retry, or noop -- see the branch table below.

    The two-query pattern is on purpose: a single
    ``INSERT ... ON CONFLICT DO UPDATE`` would conflate "row already
    terminal" with "row was just inserted" because both come back through
    ``RETURNING``. Splitting the read makes the branch unambiguous.
    """
    bind = db.get_bind()
    dialect_name = bind.dialect.name

    new_id = uuid4()
    now = datetime.now(tz=UTC)

    base_values = {
        "id": new_id,
        "automation_id": automation_id,
        "event_id": event_id,
        "status": "queued",
        "retry_count": 0,
        "worker_id": worker_id,
        "heartbeat_at": now,
        "spend_usd": Decimal("0"),
        "spend_by_source": {},
        "contract_breaches": 0,
        "created_at": now,
    }

    if dialect_name == "postgresql":
        stmt = (
            pg_insert(AutomationRun)
            .values(**base_values)
            .on_conflict_do_nothing(constraint="uq_automation_runs_automation_event")
            .returning(AutomationRun.id)
        )
    elif dialect_name == "sqlite":
        stmt = (
            sqlite_insert(AutomationRun)
            .values(**base_values)
            .on_conflict_do_nothing(
                index_elements=["automation_id", "event_id"]
            )
            .returning(AutomationRun.id)
        )
    else:
        raise NotImplementedError(
            f"_upsert_run: unsupported dialect {dialect_name!r}"
        )

    result = await db.execute(stmt)
    inserted_id = result.scalar_one_or_none()

    if inserted_id is not None:
        # We won the race; flush so subsequent SELECTs see our row inside
        # the same transaction.
        await db.flush()
        run = (
            await db.execute(
                select(AutomationRun).where(AutomationRun.id == inserted_id)
            )
        ).scalar_one()
        return run, True

    # Step 2: someone else already inserted; load the existing row.
    existing = (
        await db.execute(
            select(AutomationRun)
            .where(AutomationRun.automation_id == automation_id)
            .where(AutomationRun.event_id == event_id)
        )
    ).scalar_one()
    return existing, False


# ---------------------------------------------------------------------------
# Heartbeat helper
# ---------------------------------------------------------------------------


async def update_run_heartbeat(
    db: AsyncSession,
    run_id: UUID,
    *,
    worker_id: str | None = None,
) -> None:
    """Bump ``heartbeat_at`` on an in-flight run.

    Phase 4's controller leader sweeps runs whose heartbeat is older than
    90s. Phase 1 just writes them; the sweeper itself isn't online yet.
    Caller should ``await db.commit()`` -- we do not commit here so the
    heartbeat stays atomic with whatever else the caller is doing.
    """
    values: dict[str, Any] = {"heartbeat_at": datetime.now(tz=UTC)}
    if worker_id is not None:
        values["worker_id"] = worker_id

    await db.execute(
        update(AutomationRun).where(AutomationRun.id == run_id).values(**values)
    )


# ---------------------------------------------------------------------------
# Action executor stubs
#
# Phase 1 wires the real handlers for ``agent.run`` and ``gateway.send``;
# ``app.invoke`` calls through ``_dispatch_app_action`` which defers to
# the real ``services.apps.action_dispatcher`` when present (Wave 2B). The
# synthesis step replaces the stub with a direct import once Wave 2B's
# module lands; the dispatcher itself is unchanged.
# ---------------------------------------------------------------------------


async def _dispatch_agent_run(
    db: AsyncSession,
    *,
    run: AutomationRun,
    automation: AutomationDefinition,
    action: AutomationAction,
    event_payload: dict[str, Any],
) -> dict[str, Any]:
    """Enqueue ``execute_agent_task`` against the existing worker pipeline.

    Phase 1 keeps the agent path mostly intact -- the existing
    ``app.worker.execute_agent_task`` body runs. We pass ``contract`` and
    ``run_id`` through the payload so the worker can attribute spend and
    write status transitions to ``automation_runs``. The agent payload
    builder lives in ``services.agent_context`` and is touched in a
    sibling wave; here we only assemble the minimal envelope.
    """
    # Lazy import to avoid pulling the worker module at dispatcher import
    # time (worker pulls heavy deps -- model adapters, kubernetes clients).
    from ..task_queue import get_task_queue

    config = action.config or {}
    payload: dict[str, Any] = {
        # Mirrors AgentTaskPayload.from_dict required keys.
        "task_id": str(run.id),
        "user_id": str(automation.owner_user_id),
        "chat_id": config.get("chat_id", ""),
        "message": config.get("message", "") or event_payload.get("message", ""),
        "project_id": str(automation.target_project_id or "")
        if automation.target_project_id
        else "",
        "agent_id": config.get("agent_id"),
        "model_name": config.get("model_name", ""),
        "view_context": config.get("view_context"),
        # Phase 2 will start using these in-worker.
        "automation_run_id": str(run.id),
        "automation_id": str(automation.id),
        "contract": automation.contract,
    }

    queue = get_task_queue()
    await queue.enqueue("execute_agent_task", payload)
    return {"action_type": "agent.run", "task_id": str(run.id), "enqueued": True}


async def _dispatch_app_action(
    db: AsyncSession,
    *,
    run: AutomationRun,
    automation: AutomationDefinition,
    action: AutomationAction,
    event_payload: dict[str, Any],
) -> dict[str, Any]:
    """Defer to ``services.apps.action_dispatcher`` (Wave 2B).

    The real module is being built in a parallel wave. Until it ships,
    every ``app.invoke`` action surfaces as a typed
    :class:`NotImplementedError` so the failure path is exercised in tests.
    The synthesis step swaps this stub for a direct call once Wave 2B
    lands; nothing else in the dispatcher changes.
    """
    try:
        # The plan calls this module ``services.apps.action_dispatcher`` and
        # exposes a ``dispatch`` async coroutine. Import lazily so the
        # absence of the module never breaks dispatcher import.
        from ..apps import action_dispatcher  # type: ignore[attr-defined]
    except ImportError as exc:  # pragma: no cover - exercised once Wave 2B lands
        raise NotImplementedError(
            "app.invoke handler not available yet "
            "(services.apps.action_dispatcher belongs to Wave 2B)"
        ) from exc

    config = action.config or {}
    app_action_id = action.app_action_id
    if app_action_id is None:
        raise ContractInvalid(
            "automation_actions.app_action_id is required for action_type='app.invoke'"
        )

    return await action_dispatcher.dispatch(  # type: ignore[no-any-return]
        db,
        app_action_id=app_action_id,
        input=config.get("input", event_payload),
        run_id=run.id,
    )


async def _dispatch_gateway_send(
    db: AsyncSession,
    *,
    run: AutomationRun,
    automation: AutomationDefinition,
    action: AutomationAction,
    event_payload: dict[str, Any],
) -> dict[str, Any]:
    """Render ``result_template`` (or pass-through) and XADD to gateway stream.

    Phase 1 supports a simple ``{config.body_template}`` pass-through.
    Phase 3's long-lived render worker will replace the in-process render
    with the sandboxed Jinja IPC client; the producer side here doesn't
    change.
    """
    from ...config import get_settings
    from ..cache_service import get_redis_client
    from ..gateway.envelope import KIND_MESSAGE, build_envelope

    config = action.config or {}
    template = config.get("body_template") or config.get("body") or ""
    body = _render_simple_template(template, event_payload)

    settings = get_settings()
    redis = await get_redis_client()
    if redis is None:
        # Desktop / no-Redis mode: gateway delivery is a no-op (consumer
        # also doesn't run). Surface a sentinel so the caller can persist
        # an artifact noting the skip.
        logger.info(
            "dispatcher.gateway_send: redis unavailable, skipping XADD run=%s",
            run.id,
        )
        return {
            "action_type": "gateway.send",
            "delivered": False,
            "reason": "redis_unavailable",
            "body": body,
        }

    envelope = build_envelope(
        kind=KIND_MESSAGE,
        config_id=str(config.get("channel_config_id", "") or ""),
        session_key=str(config.get("session_key", "") or ""),
        task_id=str(run.id),
        body=body[:8000],
        artifact_refs=[],
    )
    await redis.xadd(
        settings.gateway_delivery_stream,
        envelope,
        maxlen=settings.gateway_delivery_maxlen,
    )
    return {
        "action_type": "gateway.send",
        "delivered": True,
        "body": body,
    }


def _render_simple_template(template: str, context: dict[str, Any]) -> str:
    """Minimal ``{key}`` interpolation for Phase 1.

    Phase 3 swaps this for the sandboxed Jinja render-worker IPC client.
    Until then we keep the surface tiny -- a missing key yields the
    literal placeholder rather than crashing the action so the run still
    completes and the user sees the unrendered output in run history.
    """
    if not template:
        return ""
    try:
        return template.format_map(_DefaultDict(context))
    except (ValueError, IndexError, KeyError):
        return template


class _DefaultDict(dict):
    """``str.format_map`` helper that leaves unknown keys verbatim."""

    def __missing__(self, key: str) -> str:  # pragma: no cover - trivial
        return "{" + key + "}"


# ---------------------------------------------------------------------------
# Delivery + finalization
# ---------------------------------------------------------------------------


async def _deliver_and_finalize(
    db: AsyncSession,
    *,
    run: AutomationRun,
    automation: AutomationDefinition,
    action_result: dict[str, Any],
) -> None:
    """Fan out to delivery targets and persist receipts.

    Phase 1 writes one ``automation_run_artifacts`` row per target with
    ``kind='delivery_receipt'``. Phase 4 swaps the delivery hop for the
    real ``CommunicationDestination``-backed gateway routing; the artifact
    shape stays the same so downstream rendering keeps working.
    """
    targets = (
        (
            await db.execute(
                select(AutomationDeliveryTarget)
                .where(AutomationDeliveryTarget.automation_id == automation.id)
                .order_by(AutomationDeliveryTarget.ordinal.asc())
            )
        )
        .scalars()
        .all()
    )

    rendered_body = action_result.get("body") or ""

    for target in targets:
        receipt = AutomationRunArtifact(
            id=uuid4(),
            run_id=run.id,
            kind="delivery_receipt",
            name=f"delivery:{target.destination_id}",
            mime_type="application/json",
            storage_mode="inline",
            storage_ref="",
            preview_text=rendered_body[:2000] if rendered_body else None,
            size_bytes=len(rendered_body.encode("utf-8")) if rendered_body else 0,
            meta={
                "destination_id": str(target.destination_id),
                "ordinal": target.ordinal,
                "action_result": _safe_json(action_result),
            },
        )
        db.add(receipt)


def _safe_json(value: Any) -> Any:
    """Drop anything that won't survive JSON serialization (UUIDs etc.)."""
    if isinstance(value, dict):
        return {k: _safe_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_json(v) for v in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


# Status sets used by the upsert branch table.
_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "expired", "cancelled"})
_INFLIGHT_STATUSES = frozenset({"running", "preflight"})
_RETRYABLE_STATUSES = frozenset({"paused", "expired", "cancelled", "failed_preflight"})


async def dispatch_automation(
    db: AsyncSession,
    *,
    automation_id: UUID,
    event_id: UUID,
    worker_id: str | None = None,
    force_retry: bool = False,
) -> DispatchResult:
    """Idempotently dispatch an automation event to a terminal run.

    Safe to call multiple times with the same ``(automation_id, event_id)``
    -- the upsert branch table guarantees we never re-execute work that's
    already in flight or terminal (unless ``force_retry`` is set).

    Branch table on existing run status (Phase 1):

    +----------------------------+------------------------------------------+
    | Existing status            | Action                                   |
    +============================+==========================================+
    | ``succeeded``, ``failed``  | noop -- return existing run unchanged    |
    +----------------------------+------------------------------------------+
    | ``running``, ``preflight`` | noop -- already in flight                |
    +----------------------------+------------------------------------------+
    | ``queued``                 | noop -- about-to-be in flight            |
    +----------------------------+------------------------------------------+
    | ``paused``, ``expired``,   | bump ``retry_count``, set                |
    | ``cancelled``,             | ``status='queued'``, re-enter the flow   |
    | ``failed_preflight``       |                                          |
    +----------------------------+------------------------------------------+

    ``force_retry=True`` ignores the terminal-noop branch and re-runs an
    already-finished event. This is audit-logged by callers (the manual
    "Run again" flow in the UI).
    """
    if worker_id is None:
        # Default to a host:pid pair so multi-worker pools have a
        # distinguishable stamp on heartbeat sweeps.
        worker_id = f"{socket.gethostname()}:{uuid4().hex[:8]}"

    # ---- Phase A: idempotent upsert -------------------------------------
    run, inserted = await _upsert_run(
        db,
        automation_id=automation_id,
        event_id=event_id,
        worker_id=worker_id,
    )

    if not inserted:
        # Replay path. Decide what to do based on the existing status.
        existing_status = run.status

        if existing_status in _TERMINAL_STATUSES and not force_retry:
            await db.commit()
            return DispatchResult(
                status=DispatchStatus.NOOP_TERMINAL,
                run_id=run.id,
                run_status=existing_status,
                reason=f"existing run is {existing_status}",
            )

        if existing_status in _INFLIGHT_STATUSES or existing_status == "queued":
            await db.commit()
            return DispatchResult(
                status=DispatchStatus.NOOP_INFLIGHT,
                run_id=run.id,
                run_status=existing_status,
                reason=f"existing run is {existing_status}",
            )

        # Retryable: bump the counter, reset to queued, re-enter the flow.
        if existing_status in _RETRYABLE_STATUSES or force_retry:
            await db.execute(
                update(AutomationRun)
                .where(AutomationRun.id == run.id)
                .values(
                    status="queued",
                    retry_count=AutomationRun.retry_count + 1,
                    worker_id=worker_id,
                    heartbeat_at=datetime.now(tz=UTC),
                    paused_reason=None,
                )
            )
            await db.commit()
            # Re-load so downstream sees the bumped retry_count.
            run = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == run.id)
                )
            ).scalar_one()
            # Fall through into Phase B with status='queued' again.
        else:
            # Unknown status -- treat conservatively as noop so we don't
            # corrupt anything we don't understand.
            await db.commit()
            return DispatchResult(
                status=DispatchStatus.NOOP_INFLIGHT,
                run_id=run.id,
                run_status=existing_status,
                reason=f"unknown run status {existing_status!r}",
            )
    else:
        await db.commit()

    # ---- Phase B: contract preflight -----------------------------------
    automation = (
        await db.execute(
            select(AutomationDefinition).where(
                AutomationDefinition.id == automation_id
            )
        )
    ).scalar_one_or_none()

    if automation is None or not automation.is_active:
        return await _mark_failed_preflight(
            db,
            run=run,
            reason=(
                "automation not found"
                if automation is None
                else "automation is_active=False"
            ),
            paused_status=DispatchStatus.PAUSED,
        )

    try:
        _validate_contract(automation.contract)
    except ContractInvalid as exc:
        return await _mark_failed_preflight(
            db,
            run=run,
            reason=str(exc),
            paused_status=DispatchStatus.FAILED,
        )

    # Transition queued -> preflight -> running. Two updates so the
    # state-machine is auditable; cheap on Postgres + SQLite.
    await db.execute(
        update(AutomationRun)
        .where(AutomationRun.id == run.id)
        .values(status="preflight", heartbeat_at=datetime.now(tz=UTC))
    )
    await db.commit()

    # Heartbeat once between preflight and execution -- gives the Phase 4
    # sweep a fresh timestamp before we plunge into action work that may
    # take many seconds.
    await update_run_heartbeat(db, run.id, worker_id=worker_id)
    await db.commit()

    # ---- Phase C: action execution -------------------------------------
    actions = (
        (
            await db.execute(
                select(AutomationAction)
                .where(AutomationAction.automation_id == automation_id)
                .order_by(AutomationAction.ordinal.asc())
            )
        )
        .scalars()
        .all()
    )

    if not actions:
        return await _mark_failed_preflight(
            db,
            run=run,
            reason="automation has no actions",
            paused_status=DispatchStatus.FAILED,
        )

    if len(actions) > 1:
        # Phase 1 only supports a single action (ordinal=0). The DAG form
        # ships in v2; until then we fail loudly rather than silently
        # executing only the first row.
        return await _mark_failed_preflight(
            db,
            run=run,
            reason=(
                f"phase 1 supports a single action; got {len(actions)} "
                "(DAG form lands in v2)"
            ),
            paused_status=DispatchStatus.FAILED,
        )

    action = actions[0]

    # Mark running before we route -- the executor may take a while and we
    # want the row to reflect that we're past preflight.
    started_at = datetime.now(tz=UTC)
    await db.execute(
        update(AutomationRun)
        .where(AutomationRun.id == run.id)
        .values(
            status="running",
            started_at=started_at,
            heartbeat_at=started_at,
        )
    )
    await db.commit()

    # Re-fetch so we hand a fresh row to the executor branches.
    run = (
        await db.execute(select(AutomationRun).where(AutomationRun.id == run.id))
    ).scalar_one()

    event_payload = await _load_event_payload(db, event_id)

    try:
        if action.action_type == "agent.run":
            action_result = await _dispatch_agent_run(
                db,
                run=run,
                automation=automation,
                action=action,
                event_payload=event_payload,
            )
        elif action.action_type == "app.invoke":
            action_result = await _dispatch_app_action(
                db,
                run=run,
                automation=automation,
                action=action,
                event_payload=event_payload,
            )
        elif action.action_type == "gateway.send":
            action_result = await _dispatch_gateway_send(
                db,
                run=run,
                automation=automation,
                action=action,
                event_payload=event_payload,
            )
        else:
            raise ActionDispatchFailed(
                f"unknown action_type {action.action_type!r}"
            )
    except NotImplementedError as exc:
        # app.invoke stub path while Wave 2B is in flight.
        return await _finalize_failure(
            db,
            run=run,
            reason=f"action_dispatcher unavailable: {exc}",
        )
    except DispatcherError as exc:
        return await _finalize_failure(db, run=run, reason=str(exc))
    except Exception as exc:
        logger.exception(
            "dispatcher.action_failed automation=%s event=%s run=%s",
            automation_id,
            event_id,
            run.id,
        )
        return await _finalize_failure(db, run=run, reason=repr(exc)[:1000])

    # ---- Phase D: delivery + finalization ------------------------------
    try:
        await _deliver_and_finalize(
            db,
            run=run,
            automation=automation,
            action_result=action_result,
        )
    except Exception as exc:
        logger.exception(
            "dispatcher.delivery_failed automation=%s run=%s",
            automation_id,
            run.id,
        )
        return await _finalize_failure(
            db,
            run=run,
            reason=f"delivery failed: {exc!r}",
        )

    ended_at = datetime.now(tz=UTC)
    await db.execute(
        update(AutomationRun)
        .where(AutomationRun.id == run.id)
        .values(
            status="succeeded",
            ended_at=ended_at,
            heartbeat_at=ended_at,
            raw_output=_safe_json(action_result),
        )
    )
    await db.commit()

    return DispatchResult(
        status=DispatchStatus.SUCCEEDED,
        run_id=run.id,
        run_status="succeeded",
    )


# ---------------------------------------------------------------------------
# Internal finalization helpers
# ---------------------------------------------------------------------------


async def _mark_failed_preflight(
    db: AsyncSession,
    *,
    run: AutomationRun,
    reason: str,
    paused_status: DispatchStatus,
) -> DispatchResult:
    """Transition a run into ``failed_preflight`` and return a typed result."""
    ended_at = datetime.now(tz=UTC)
    await db.execute(
        update(AutomationRun)
        .where(AutomationRun.id == run.id)
        .values(
            status="failed_preflight",
            paused_reason=reason,
            ended_at=ended_at,
            heartbeat_at=ended_at,
        )
    )
    await db.commit()
    return DispatchResult(
        status=paused_status,
        run_id=run.id,
        run_status="failed_preflight",
        reason=reason,
    )


async def _finalize_failure(
    db: AsyncSession,
    *,
    run: AutomationRun,
    reason: str,
) -> DispatchResult:
    """Transition a run into ``failed`` after action/delivery error."""
    ended_at = datetime.now(tz=UTC)
    await db.execute(
        update(AutomationRun)
        .where(AutomationRun.id == run.id)
        .values(
            status="failed",
            paused_reason=reason,
            ended_at=ended_at,
            heartbeat_at=ended_at,
        )
    )
    await db.commit()
    return DispatchResult(
        status=DispatchStatus.FAILED,
        run_id=run.id,
        run_status="failed",
        reason=reason,
    )


async def _load_event_payload(db: AsyncSession, event_id: UUID) -> dict[str, Any]:
    """Best-effort fetch of the event payload for template rendering.

    We don't fail the dispatch if the event row was reaped between the
    upsert and the action -- we just hand the executor an empty dict and
    log the skip so the run still completes.
    """
    from ...models_automations import AutomationEvent

    event = (
        await db.execute(
            select(AutomationEvent).where(AutomationEvent.id == event_id)
        )
    ).scalar_one_or_none()
    if event is None:
        logger.warning(
            "dispatcher: event %s not found, using empty payload",
            event_id,
        )
        return {}
    return dict(event.payload or {})
