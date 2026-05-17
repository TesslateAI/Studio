"""Append-only run-event log writer (Phase C, issue #472).

One function per event kind. Each function writes a row to
``automation_run_events`` and commits. Failures are swallowed and
logged: the event log is observability, not control plane, so a write
hiccup must never abort a run.

Callers (engine, worker, action_dispatcher, agent_approval, budget,
delivery) emit events at well-known boundaries. Run history reads the
table sorted by ``ts ASC`` to render the timeline.

The module exposes both a low-level ``record`` primitive and a set of
named ``emit_*`` helpers. New event kinds add a new helper plus an
entry in :class:`EventKind` plus a CHECK constraint update on the
table (next migration).
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models_automations import AutomationRunEvent

logger = logging.getLogger(__name__)


class EventKind:
    """Canonical kinds. Mirrors the CHECK on automation_run_events.kind."""

    RUN_STARTED = "run.started"
    RUN_FINISHED = "run.finished"
    STEP_STARTED = "step.started"
    STEP_FINISHED = "step.finished"
    TOOL_CALLED = "tool.called"
    CONNECTOR_TOUCHED = "connector.touched"
    APP_INVOKED = "app.invoked"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_RESOLVED = "approval.resolved"
    ARTIFACT_PRODUCED = "artifact.produced"
    DELIVERY_SENT = "delivery.sent"
    BUDGET_CONSUMED = "budget.consumed"
    ERROR_RAISED = "error.raised"


async def record(
    db: AsyncSession,
    *,
    run_id: Any,
    kind: str,
    actor: str | None = None,
    step_run_id: Any | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Insert one event row. Best-effort; never raises out of the helper.

    The caller is expected to be inside its own transaction context;
    we commit at the end so the event is durable regardless of the
    caller's outcome (e.g. an error.raised event must persist even if
    the run write that follows it rolls back).
    """
    try:
        evt = AutomationRunEvent(
            id=uuid.uuid4(),
            automation_run_id=run_id,
            step_run_id=step_run_id,
            kind=kind,
            actor=actor,
            payload=_safe_json(payload) if payload else {},
        )
        db.add(evt)
        await db.commit()
    except Exception as exc:
        logger.warning(
            "event_log.record failed run=%s kind=%s err=%r",
            run_id,
            kind,
            exc,
        )
        # Best-effort rollback so the caller's session is still usable.
        with contextlib.suppress(Exception):
            await db.rollback()


# ----------------------------------------------------------------------
# Named helpers — keep the call sites readable and the payloads
# self-documenting. Adding a new kind = add a constant on EventKind +
# add a helper here + extend the CHECK constraint in the next migration.
# ----------------------------------------------------------------------


async def emit_step_started(
    db: AsyncSession,
    *,
    run_id: Any,
    step_run_id: Any,
    ordinal: int,
    kind: str,
    actor: str = "engine",
) -> None:
    await record(
        db,
        run_id=run_id,
        step_run_id=step_run_id,
        kind=EventKind.STEP_STARTED,
        actor=actor,
        payload={"ordinal": ordinal, "step_kind": kind},
    )


async def emit_step_finished(
    db: AsyncSession,
    *,
    run_id: Any,
    step_run_id: Any,
    ordinal: int,
    kind: str,
    status: str,
    spend_usd: Decimal | None = None,
    actor: str = "engine",
) -> None:
    await record(
        db,
        run_id=run_id,
        step_run_id=step_run_id,
        kind=EventKind.STEP_FINISHED,
        actor=actor,
        payload={
            "ordinal": ordinal,
            "step_kind": kind,
            "status": status,
            "spend_usd": str(spend_usd) if spend_usd is not None else None,
        },
    )


async def emit_tool_called(
    db: AsyncSession,
    *,
    run_id: Any,
    step_run_id: Any | None,
    tool_name: str,
    actor: str | None = None,
) -> None:
    await record(
        db,
        run_id=run_id,
        step_run_id=step_run_id,
        kind=EventKind.TOOL_CALLED,
        actor=actor,
        payload={"tool": tool_name},
    )


async def emit_connector_touched(
    db: AsyncSession,
    *,
    run_id: Any,
    step_run_id: Any | None,
    connector_id: str,
    method: str | None = None,
    actor: str | None = None,
) -> None:
    await record(
        db,
        run_id=run_id,
        step_run_id=step_run_id,
        kind=EventKind.CONNECTOR_TOUCHED,
        actor=actor,
        payload={"connector_id": connector_id, "method": method},
    )


async def emit_app_invoked(
    db: AsyncSession,
    *,
    run_id: Any,
    step_run_id: Any | None,
    app_instance_id: str,
    action_name: str,
    actor: str | None = None,
) -> None:
    await record(
        db,
        run_id=run_id,
        step_run_id=step_run_id,
        kind=EventKind.APP_INVOKED,
        actor=actor,
        payload={
            "app_instance_id": app_instance_id,
            "action_name": action_name,
        },
    )


async def emit_approval_requested(
    db: AsyncSession,
    *,
    run_id: Any,
    step_run_id: Any | None,
    tool_name: str | None,
    reason: str | None,
    actor: str = "engine",
) -> None:
    await record(
        db,
        run_id=run_id,
        step_run_id=step_run_id,
        kind=EventKind.APPROVAL_REQUESTED,
        actor=actor,
        payload={"tool": tool_name, "reason": reason},
    )


async def emit_approval_resolved(
    db: AsyncSession,
    *,
    run_id: Any,
    step_run_id: Any | None,
    decision: str,
    approver_user_id: str | None = None,
) -> None:
    actor = f"approver:{approver_user_id}" if approver_user_id else "approver"
    await record(
        db,
        run_id=run_id,
        step_run_id=step_run_id,
        kind=EventKind.APPROVAL_RESOLVED,
        actor=actor,
        payload={"decision": decision},
    )


async def emit_artifact_produced(
    db: AsyncSession,
    *,
    run_id: Any,
    step_run_id: Any | None,
    artifact_id: str,
    artifact_kind: str,
    actor: str | None = None,
) -> None:
    await record(
        db,
        run_id=run_id,
        step_run_id=step_run_id,
        kind=EventKind.ARTIFACT_PRODUCED,
        actor=actor,
        payload={"artifact_id": artifact_id, "kind": artifact_kind},
    )


async def emit_delivery_sent(
    db: AsyncSession,
    *,
    run_id: Any,
    step_run_id: Any | None,
    destination_kind: str,
    destination_id: str | None = None,
    actor: str = "engine",
) -> None:
    await record(
        db,
        run_id=run_id,
        step_run_id=step_run_id,
        kind=EventKind.DELIVERY_SENT,
        actor=actor,
        payload={
            "destination_kind": destination_kind,
            "destination_id": destination_id,
        },
    )


async def emit_budget_consumed(
    db: AsyncSession,
    *,
    run_id: Any,
    step_run_id: Any | None,
    amount_usd: Decimal,
    source: str | None = None,
    actor: str | None = None,
) -> None:
    await record(
        db,
        run_id=run_id,
        step_run_id=step_run_id,
        kind=EventKind.BUDGET_CONSUMED,
        actor=actor,
        payload={
            "amount_usd": str(amount_usd),
            "source": source,
        },
    )


async def emit_run_finished(
    db: AsyncSession,
    *,
    run_id: Any,
    automation_id: Any,
    status: str,
    reason: str | None = None,
) -> None:
    """Terminal run event + workflow_event fan-out (G5 #469).

    ``status`` is the final ``automation_runs.status`` value
    (``succeeded``, ``failed``, ``failed_preflight``, ``cancelled``,
    ``timed_out``). When the run did not succeed, we synthesise a
    ``run.failed`` workflow_event so per-workflow doctor subscribers
    fire on terminal failures — not just per-step ``error.raised``.

    Fan-out is best-effort and never raises out of the helper.
    """
    payload: dict[str, Any] = {"status": status}
    if reason:
        payload["reason"] = reason
    await record(db, run_id=run_id, kind=EventKind.RUN_FINISHED, payload=payload)

    if status not in ("succeeded",) and automation_id is not None:
        try:
            from ..triggers.workflow_event import route_workflow_event

            await route_workflow_event(
                db,
                source_automation_id=automation_id,
                source_run_id=run_id,
                event_kind="run.failed",
                payload=payload,
            )
        except Exception as exc:
            logger.warning(
                "emit_run_finished.workflow_event_dispatch_failed run=%s err=%r",
                run_id,
                exc,
            )


async def emit_error(
    db: AsyncSession,
    *,
    run_id: Any,
    step_run_id: Any | None,
    error_type: str,
    message: str,
    actor: str | None = None,
    automation_id: Any | None = None,
) -> None:
    await record(
        db,
        run_id=run_id,
        step_run_id=step_run_id,
        kind=EventKind.ERROR_RAISED,
        actor=actor,
        payload={"error_type": error_type, "message": message[:1000]},
    )
    # G5 (#469): fire workflow_event subscribers on error. The doctor
    # for this automation (if any) gets dispatched. Best-effort —
    # subscriber failures must not propagate back to the failing run.
    if automation_id is not None:
        try:
            from ..triggers.workflow_event import route_workflow_event

            await route_workflow_event(
                db,
                source_automation_id=automation_id,
                source_run_id=run_id,
                event_kind="error.raised",
                payload={"error_type": error_type, "message": message[:1000]},
            )
        except Exception as exc:
            logger.warning(
                "emit_error.workflow_event_dispatch_failed automation=%s err=%r",
                automation_id,
                exc,
            )


def _safe_json(value: Any) -> Any:
    """Coerce non-JSON-serializable values (Decimal, UUID) to strings."""
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(k): _safe_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_json(v) for v in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
