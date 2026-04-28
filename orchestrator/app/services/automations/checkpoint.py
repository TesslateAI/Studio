"""Phase 2 — non-blocking HITL checkpoint serialization + hydration.

When :class:`~app.agent.tools.contract_gate.ContractGate` denies a tool call
mid-run (or when an :func:`._dispatch_app_action` / :func:`._dispatch_gateway_send`
preflight fires), the dispatcher MUST exit cleanly so the ARQ worker slot is
released. The run lives on as a row in ``automation_runs`` with
``status='waiting_approval'`` plus a serialized snapshot of "everything we'd
need to keep going" in :attr:`AutomationRun.checkpoint`.

This module is the contract between:

* the dispatcher (writes the checkpoint at pause time, see
  :func:`serialize_checkpoint`),
* the approval-resolution endpoint (creates an
  :class:`AutomationApprovalRequest`; the user picks an option),
* the resume worker task (loads the checkpoint with :func:`hydrate_checkpoint`
  and re-enters via :func:`dispatcher.resume_run`).

MVP resume boundary
-------------------

The plan deliberately ships a *narrow, honest* resume surface. Three resume
strategies, picked by :func:`determine_resume_strategy`:

================================ ================================================================
``redispatch``                   Re-call the action dispatcher with the original input. Used for
                                 ``app.invoke`` and ``gateway.send`` (idempotent on the input).
``agent_continue``               ``agent.run`` where every in-flight tool was
                                 ``state_serializable=True``. Re-instantiate the agent loop
                                 with the saved ``message_history`` + ``tool_result_trail``.
``restart_from_checkpoint``      ``agent.run`` where ANY in-flight tool was
                                 ``state_serializable=False``. The in-flight tool was cancelled
                                 at the breach point. We restart the agent loop fresh and
                                 *only* allow ``cancel_run`` or
                                 ``restart_from_last_checkpoint`` resolutions.
================================ ================================================================

Everything serialized here is JSON-safe: UUIDs become strings, ``Decimal``
becomes ``str``, ``datetime`` becomes ``isoformat()``. The
:class:`AutomationRun.checkpoint` column is JSONB on Postgres and JSON on
SQLite — both happy with the standard library encoder.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models_automations import AutomationRun

logger = logging.getLogger(__name__)


__all__ = [
    "RunCheckpoint",
    "ResumeStrategy",
    "serialize_checkpoint",
    "hydrate_checkpoint",
    "determine_resume_strategy",
]


# Sentinel strings — kept narrow so callers can branch with string equality
# and downstream telemetry stays cardinality-bounded. Mirror the BreachKind
# convention in contract_gate.py.
class ResumeStrategy:
    REDISPATCH = "redispatch"
    AGENT_CONTINUE = "agent_continue"
    RESTART_FROM_CHECKPOINT = "restart_from_checkpoint"


_VALID_ACTION_TYPES = frozenset({"agent.run", "app.invoke", "gateway.send"})


@dataclass(frozen=True)
class RunCheckpoint:
    """Serializable snapshot of an in-flight :class:`AutomationRun` at the
    approval boundary.

    All fields are JSON-portable when serialized via :func:`_to_json_dict` —
    UUIDs become strings, ``Decimal`` becomes a string, ``datetime`` becomes
    ``isoformat()``. Hydration via :func:`hydrate_checkpoint` reverses the
    transform.

    Attributes:
        run_id: :class:`AutomationRun.id`.
        automation_id: :class:`AutomationDefinition.id`.
        action_type: One of ``agent.run``, ``app.invoke``, ``gateway.send``.
        paused_at: When the breach fired (``UTC``).
        pause_reason: Human-readable reason — surfaced in run history.
        resume_strategy: One of :class:`ResumeStrategy` constants. Set at
            serialize time so the resume worker can branch without re-running
            the decision logic against a possibly-mutated contract.
        action_state: Action-specific state (see resume-strategy table). For
            ``agent.run`` this includes ``message_history`` (list[dict]),
            ``tool_result_trail`` (list[dict]), ``current_step`` (int), and
            ``in_flight_non_serializable_tools`` (list[str]). For
            ``app.invoke`` it includes ``input`` (dict),
            ``app_action_id`` (str UUID), and optional ``partial_output``.
            For ``gateway.send`` it includes ``body`` (str) and
            ``destination_id`` (str UUID).
        invocation_subject_id: When set, the Wave-1B
            :class:`InvocationSubject` row id — keeps payer/credit attribution
            stable across the pause.
        budget_allocation: Serialized :class:`BudgetAllocation` (from
            :mod:`.budget`); resume reuses the same key id when the run
            continues.
        contract_snapshot: The contract dict at pause time. Used by the
            resume worker to short-circuit tool-allowlist re-checks if the
            user's approval response includes a scope_modifications delta
            and the underlying definition has been edited concurrently.
    """

    run_id: UUID
    automation_id: UUID
    action_type: str
    paused_at: datetime
    pause_reason: str
    resume_strategy: str

    action_state: dict[str, Any]

    invocation_subject_id: UUID | None = None
    budget_allocation: dict[str, Any] | None = None
    contract_snapshot: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Resume-strategy decision
# ---------------------------------------------------------------------------


def determine_resume_strategy(
    action_type: str,
    action_state: dict[str, Any],
    contract_snapshot: dict[str, Any],
) -> str:
    """Decide which resume path applies.

    The single load-bearing question is:

    * For ``agent.run``, were any of the in-flight tools at the moment of
      breach annotated ``state_serializable=False``? If yes, the in-flight
      tool was cancelled and we cannot replay it — the only honest resume
      is to restart the agent loop from the last completed checkpoint
      (which the agent runtime persists per-step).
    * Otherwise we re-instantiate the agent loop with the saved
      message_history + tool_result_trail.
    * For ``app.invoke`` / ``gateway.send`` the action is idempotent on its
      input — we just re-call the dispatcher with the saved payload.

    The decision is captured at serialize time and stored on the checkpoint
    so a contract edit between pause and resume can't silently change which
    code path runs.
    """
    if action_type in {"app.invoke", "gateway.send"}:
        return ResumeStrategy.REDISPATCH

    if action_type == "agent.run":
        in_flight_ns = action_state.get("in_flight_non_serializable_tools") or []
        if in_flight_ns:
            return ResumeStrategy.RESTART_FROM_CHECKPOINT
        return ResumeStrategy.AGENT_CONTINUE

    # Defensive: unknown action types resolve to restart so we don't replay
    # an action we don't understand the idempotency of. Logged loudly so
    # the synthesis step catches it.
    logger.warning(
        "[checkpoint] determine_resume_strategy: unknown action_type=%r; "
        "defaulting to restart_from_checkpoint",
        action_type,
    )
    return ResumeStrategy.RESTART_FROM_CHECKPOINT


# ---------------------------------------------------------------------------
# Serialize + persist
# ---------------------------------------------------------------------------


async def serialize_checkpoint(
    db: AsyncSession,
    *,
    run: AutomationRun,
    action_type: str,
    action_state: dict[str, Any],
    pause_reason: str,
    contract_snapshot: dict[str, Any] | None = None,
    invocation_subject_id: UUID | None = None,
    budget_allocation: Any | None = None,
) -> RunCheckpoint:
    """Build a :class:`RunCheckpoint` and persist it to
    :attr:`AutomationRun.checkpoint`.

    Caller (the dispatcher) is responsible for ``await db.commit()`` so the
    checkpoint write stays atomic with the status transition + approval
    request insert. We deliberately do NOT commit here.

    ``budget_allocation`` may be a :class:`~.budget.BudgetAllocation` dataclass
    or already a dict; either form is normalized to a JSON-safe dict.
    """
    if action_type not in _VALID_ACTION_TYPES:
        raise ValueError(
            f"serialize_checkpoint: action_type must be one of "
            f"{sorted(_VALID_ACTION_TYPES)!r}, got {action_type!r}"
        )

    contract = dict(contract_snapshot or {})
    safe_state = _to_json_dict(action_state)
    resume_strategy = determine_resume_strategy(action_type, safe_state, contract)
    paused_at = datetime.now(tz=UTC)

    budget_dict: dict[str, Any] | None = None
    if budget_allocation is not None:
        budget_dict = _serialize_budget_allocation(budget_allocation)

    checkpoint = RunCheckpoint(
        run_id=run.id,
        automation_id=run.automation_id,
        action_type=action_type,
        paused_at=paused_at,
        pause_reason=pause_reason,
        resume_strategy=resume_strategy,
        action_state=safe_state,
        invocation_subject_id=invocation_subject_id,
        budget_allocation=budget_dict,
        contract_snapshot=_to_json_dict(contract),
    )

    payload = _checkpoint_to_jsonable(checkpoint)
    # Round-trip through json to guarantee JSONB-clean (catches Decimal,
    # datetime, UUID slips early at the dispatcher boundary).
    payload = json.loads(json.dumps(payload))

    await db.execute(
        update(AutomationRun)
        .where(AutomationRun.id == run.id)
        .values(checkpoint=payload)
    )
    return checkpoint


async def hydrate_checkpoint(
    db: AsyncSession,
    *,
    run_id: UUID,
) -> RunCheckpoint | None:
    """Load and deserialize the checkpoint for ``run_id``.

    Returns ``None`` when the run row is missing or has no checkpoint stored
    (a fresh run that never paused). The resume worker treats ``None`` as a
    "nothing to do" signal — logged but not raised so ARQ doesn't retry.
    """
    row = (
        await db.execute(
            select(AutomationRun.checkpoint).where(AutomationRun.id == run_id)
        )
    ).first()

    if row is None:
        return None
    raw = row[0]
    if raw is None:
        return None
    if isinstance(raw, str):
        # Some SQLite paths return JSON columns as strings — defensive parse.
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                "[checkpoint] hydrate_checkpoint: malformed JSON for run=%s",
                run_id,
            )
            return None

    if not isinstance(raw, dict):
        logger.warning(
            "[checkpoint] hydrate_checkpoint: non-object payload type=%s for run=%s",
            type(raw).__name__,
            run_id,
        )
        return None

    return _checkpoint_from_jsonable(raw)


# ---------------------------------------------------------------------------
# Internal serialization helpers
# ---------------------------------------------------------------------------


def _serialize_budget_allocation(allocation: Any) -> dict[str, Any]:
    """Normalize a ``BudgetAllocation`` (or compatible dict) to a JSON-safe dict.

    We don't import :class:`~.budget.BudgetAllocation` directly because it
    would create an import cycle (budget.py imports from the same package).
    Duck-typing on the attribute names is enough.
    """
    if isinstance(allocation, dict):
        return _to_json_dict(allocation)

    fields = (
        "litellm_key_id",
        "litellm_key_value",
        "max_usd_per_run",
        "daily_remaining_usd",
        "is_extension",
    )
    out: dict[str, Any] = {}
    for name in fields:
        if hasattr(allocation, name):
            out[name] = _to_json_value(getattr(allocation, name))
    return out


def _checkpoint_to_jsonable(cp: RunCheckpoint) -> dict[str, Any]:
    return {
        "run_id": str(cp.run_id),
        "automation_id": str(cp.automation_id),
        "action_type": cp.action_type,
        "paused_at": cp.paused_at.isoformat(),
        "pause_reason": cp.pause_reason,
        "resume_strategy": cp.resume_strategy,
        "action_state": _to_json_dict(cp.action_state),
        "invocation_subject_id": (
            str(cp.invocation_subject_id) if cp.invocation_subject_id else None
        ),
        "budget_allocation": (
            _to_json_dict(cp.budget_allocation) if cp.budget_allocation else None
        ),
        "contract_snapshot": _to_json_dict(cp.contract_snapshot),
        "schema_version": 1,
    }


def _checkpoint_from_jsonable(raw: dict[str, Any]) -> RunCheckpoint:
    paused_raw = raw.get("paused_at")
    if isinstance(paused_raw, str):
        try:
            paused_at = datetime.fromisoformat(paused_raw)
        except ValueError:
            paused_at = datetime.now(tz=UTC)
    elif isinstance(paused_raw, datetime):
        paused_at = paused_raw
    else:
        paused_at = datetime.now(tz=UTC)

    if paused_at.tzinfo is None:
        paused_at = paused_at.replace(tzinfo=UTC)

    invocation_id = raw.get("invocation_subject_id")
    invocation_uuid = UUID(invocation_id) if invocation_id else None

    return RunCheckpoint(
        run_id=UUID(raw["run_id"]),
        automation_id=UUID(raw["automation_id"]),
        action_type=raw["action_type"],
        paused_at=paused_at,
        pause_reason=raw.get("pause_reason", ""),
        resume_strategy=raw.get("resume_strategy", ResumeStrategy.RESTART_FROM_CHECKPOINT),
        action_state=dict(raw.get("action_state") or {}),
        invocation_subject_id=invocation_uuid,
        budget_allocation=raw.get("budget_allocation"),
        contract_snapshot=dict(raw.get("contract_snapshot") or {}),
    )


def _to_json_value(value: Any) -> Any:
    """Recursive JSON-coercion mirroring ``dispatcher._safe_json``."""
    if isinstance(value, dict):
        return {k: _to_json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_value(v) for v in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    # Fallback: stringify so we never crash a checkpoint write on an exotic
    # object slipped through by a future tool wrapper.
    return str(value)


def _to_json_dict(value: Any) -> dict[str, Any]:
    coerced = _to_json_value(value)
    if not isinstance(coerced, dict):
        return {}
    return coerced
