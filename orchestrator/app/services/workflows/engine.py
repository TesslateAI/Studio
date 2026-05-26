"""Workflow engine.

Drives a multi-step :class:`~app.models_automations.AutomationDefinition`
to completion by walking its :class:`~app.models_automations.AutomationAction`
rows in ordinal order, invoking the registered :class:`StepHandler` per
step, and persisting an :class:`~app.models_automations.AutomationStepRun`
row per step.

Phase A scope (issue #470): linear ordinal walk, synchronous step kinds
only. Tier-0 ``agent.run`` (which enqueues an ARQ task and returns
``{"enqueued": True}``) is rejected with a clear error if it appears
mid-graph. Tier-0 single-step automations stay on the legacy
single-action dispatcher path and are unaffected.

Phase B will wire the worker callback so an async step can advance the
engine. Phase F adds DAG kinds (``branch``, ``parallel``,
``sub_workflow``).

Public surface:
    :func:`execute_workflow` — invoked by ``services/automations/dispatcher.py``
    when ``len(actions) > 1``. Returns the final step's output dict so
    the dispatcher can pass it to ``_deliver_and_finalize`` unchanged.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent.tools.contract_gate import ContractBreachException
from ...models_automations import (
    AutomationAction,
    AutomationDefinition,
    AutomationRun,
    AutomationStepRun,
)
from . import event_log
from .handlers import StepContext, registry  # noqa: F401  ensures handlers are imported
from .handlers.base import get_handler
from .versions import materialize_actions_from_version

logger = logging.getLogger(__name__)


class WorkflowEngineError(Exception):
    """Engine-level failure that the dispatcher should treat as a run failure."""


class AsyncStepInMultiStepError(WorkflowEngineError):
    """Raised when a multi-step workflow contains a step that handed off async.

    Phase A only supports synchronous step kinds in multi-step workflows.
    Tier-0 ``agent.run`` returns ``{"enqueued": True}`` and the worker
    closes the run later — until Phase B wires the worker callback into
    the engine, chaining a next step after that handoff would silently
    drop work.
    """


class UnknownStepKindError(WorkflowEngineError):
    """Raised when an action's ``action_type`` has no registered handler."""


async def execute_workflow(
    db: AsyncSession,
    *,
    run: AutomationRun,
    automation: AutomationDefinition,
    event_payload: dict[str, Any],
    budget_allocation: Any | None,
) -> dict[str, Any]:
    """Walk the automation's actions and execute each as a workflow step.

    Returns the FINAL step's output dict so the caller (the legacy
    dispatcher) can pass it to ``_deliver_and_finalize`` unchanged.

    Raises:
        ContractBreachException: bubbles up from a handler when a tool
            call requires approval. The dispatcher's existing
            ``_checkpoint_and_pause`` path catches this and pauses the run.
        AsyncStepInMultiStepError: a step handed off asynchronously. The
            run is marked failed with a clear reason; Phase B closes
            this gap.
        UnknownStepKindError: an action's ``action_type`` has no
            registered handler.
    """
    # G1 (#469): if the run is version-bound, read the actions from
    # the WorkflowVersion snapshot instead of the live rows. The
    # snapshot is authoritative for past runs — live rows may have
    # moved on since this run was queued. Single code path until we
    # hit the materialize fork.
    actions: list[Any]
    if getattr(run, "workflow_version_id", None) is not None:
        from ...models_workflows import WorkflowVersion

        version = (
            await db.execute(
                select(WorkflowVersion).where(WorkflowVersion.id == run.workflow_version_id)
            )
        ).scalar_one_or_none()
        if version is None:
            # Stamped a version id we can't find. Fall back to live
            # rows so the run still completes rather than orphaning.
            logger.warning(
                "workflow_engine.version_missing run=%s version_id=%s falling back to live actions",
                run.id,
                run.workflow_version_id,
            )
            actions = list(
                (
                    await db.execute(
                        select(AutomationAction)
                        .where(AutomationAction.automation_id == automation.id)
                        .order_by(AutomationAction.ordinal.asc())
                    )
                )
                .scalars()
                .all()
            )
        else:
            actions = list(materialize_actions_from_version(version))
    else:
        actions = list(
            (
                await db.execute(
                    select(AutomationAction)
                    .where(AutomationAction.automation_id == automation.id)
                    .order_by(AutomationAction.ordinal.asc())
                )
            )
            .scalars()
            .all()
        )
    if len(actions) <= 1:
        raise WorkflowEngineError(
            "execute_workflow called with a single-action automation; "
            "the dispatcher should keep these on the legacy path"
        )

    prior_outputs: list[dict[str, Any]] = []
    last_output: dict[str, Any] = {}

    # Phase F: index by ordinal so ``branch`` / future ``goto`` can
    # redirect the walker. The linear loop becomes an indexed loop;
    # without a ``next_ordinal`` directive the engine still advances
    # in the natural order of ``actions``.
    by_ordinal = {action.ordinal: action for action in actions}
    sorted_ordinals = sorted(by_ordinal.keys())
    cursor = 0
    skipped: set[int] = set()

    while cursor < len(sorted_ordinals):
        ordinal = sorted_ordinals[cursor]
        if ordinal in skipped:
            cursor += 1
            continue
        action = by_ordinal[ordinal]

        try:
            handler_cls = get_handler(action.action_type)
        except KeyError as exc:
            raise UnknownStepKindError(str(exc)) from exc

        step_run = await _begin_step_run(db, run=run, action=action)
        await event_log.emit_step_started(
            db,
            run_id=run.id,
            step_run_id=step_run.id,
            ordinal=action.ordinal,
            kind=action.action_type,
        )
        handler = handler_cls()
        ctx = StepContext(
            db=db,
            run=run,
            automation=automation,
            action=action,
            event_payload=event_payload,
            budget_allocation=budget_allocation,
            prior_step_outputs=list(prior_outputs),
        )

        try:
            result = await handler.execute(ctx)
        except ContractBreachException as exc:
            await _mark_step_status(
                db,
                step_run_id=step_run.id,
                status="awaiting_approval",
            )
            await event_log.emit_step_finished(
                db,
                run_id=run.id,
                step_run_id=step_run.id,
                ordinal=action.ordinal,
                kind=action.action_type,
                status="awaiting_approval",
            )
            await event_log.emit_approval_requested(
                db,
                run_id=run.id,
                step_run_id=step_run.id,
                tool_name=getattr(exc, "tool_name", None),
                reason=getattr(getattr(exc, "decision", None), "reason", None),
            )
            raise
        except Exception as exc:
            logger.exception(
                "workflow_engine.step_failed run=%s action=%s ordinal=%s",
                run.id,
                action.id,
                action.ordinal,
            )
            await _mark_step_status(
                db,
                step_run_id=step_run.id,
                status="failed",
                error=repr(exc)[:1000],
            )
            await event_log.emit_step_finished(
                db,
                run_id=run.id,
                step_run_id=step_run.id,
                ordinal=action.ordinal,
                kind=action.action_type,
                status="failed",
            )
            await event_log.emit_error(
                db,
                run_id=run.id,
                step_run_id=step_run.id,
                error_type=type(exc).__name__,
                message=str(exc),
            )
            raise

        if result.async_handoff:
            await _mark_step_status(
                db,
                step_run_id=step_run.id,
                status="failed",
                error=(
                    "phase A workflow engine refuses async-handoff steps in "
                    "multi-step workflows; tier-0 agent.run chaining lands "
                    "in phase B"
                ),
            )
            await event_log.emit_step_finished(
                db,
                run_id=run.id,
                step_run_id=step_run.id,
                ordinal=action.ordinal,
                kind=action.action_type,
                status="failed",
            )
            raise AsyncStepInMultiStepError(
                f"step ordinal={action.ordinal} kind={action.action_type!r} "
                "returned an async handoff; multi-step workflows require "
                "synchronous steps (worker-callback resumption lands later)"
            )

        await _mark_step_status(
            db,
            step_run_id=step_run.id,
            status="succeeded",
            output=result.output,
        )
        await event_log.emit_step_finished(
            db,
            run_id=run.id,
            step_run_id=step_run.id,
            ordinal=action.ordinal,
            kind=action.action_type,
            status="succeeded",
            spend_usd=result.spend_usd,
        )

        prior_outputs.append(result.output)
        last_output = result.output

        # Phase F: a control-flow step (branch) can redirect the engine.
        # When the target ordinal exists, mark every ordinal between
        # the current cursor and the target as skipped (forward jumps
        # only — backward jumps are rejected to avoid loops).
        if result.next_ordinal is not None and result.next_ordinal in by_ordinal:
            target = result.next_ordinal
            if target > ordinal:
                for skip_ord in sorted_ordinals:
                    if ordinal < skip_ord < target:
                        skipped.add(skip_ord)
            else:
                logger.warning(
                    "workflow_engine.branch_backward_ignored run=%s ordinal=%s target=%s",
                    run.id,
                    ordinal,
                    target,
                )

        cursor += 1

    return last_output


async def _begin_step_run(
    db: AsyncSession,
    *,
    run: AutomationRun,
    action: AutomationAction,
) -> AutomationStepRun:
    """Insert a step-run row in ``running`` status and return it."""
    step_run = AutomationStepRun(
        id=uuid.uuid4(),
        automation_run_id=run.id,
        automation_action_id=action.id,
        ordinal=action.ordinal,
        kind=action.action_type,
        status="running",
        started_at=datetime.now(tz=UTC),
        input=_safe_json(action.config),
    )
    db.add(step_run)
    await db.commit()
    await db.refresh(step_run)
    return step_run


async def _mark_step_status(
    db: AsyncSession,
    *,
    step_run_id: Any,
    status: str,
    output: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Update a step-run row with terminal (or pause) status."""
    values: dict[str, Any] = {"status": status}
    now = datetime.now(tz=UTC)
    if status in {"succeeded", "failed", "cancelled", "skipped"}:
        values["ended_at"] = now
    if output is not None:
        values["output"] = _safe_json(output)
    if error is not None:
        values["error"] = error
    await db.execute(
        update(AutomationStepRun).where(AutomationStepRun.id == step_run_id).values(**values)
    )
    await db.commit()


def _safe_json(value: Any) -> Any:
    """Best-effort JSON-serializable copy.

    The action config is already JSON-typed, but action_results from
    handlers may include ``Decimal`` or ``UUID`` values. We coerce them
    to strings so the row insert does not blow up on the JSON encoder.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(k): _safe_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_json(v) for v in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
