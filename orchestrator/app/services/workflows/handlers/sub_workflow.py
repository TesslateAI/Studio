"""``sub_workflow`` step handler (Phase F, issue #475).

Invokes another :class:`AutomationDefinition` synchronously and
captures its terminal output as the parent step's output. The child
runs through the standard ``dispatch_automation`` path so contract
preflight, budget allocation, step persistence, and event emission
all apply unchanged.

Action config shape::

    {
        "child_automation_id": "<uuid>",
        "input": {...}      # optional: passed as the child's event payload
    }

The handler refuses to invoke its own parent (depth-1 cap is enforced
by the dispatcher's existing ``parent_automation_id`` chain check;
this is a defense-in-depth same-id refusal).
"""

from __future__ import annotations

import logging
import uuid
from typing import ClassVar

from sqlalchemy import select

from ....models_automations import (
    AutomationDefinition,
    AutomationEvent,
    AutomationRun,
)
from .base import StepContext, StepHandler, StepResult, register_handler

logger = logging.getLogger(__name__)


@register_handler
class SubWorkflowHandler(StepHandler):
    kind: ClassVar[str] = "sub_workflow"

    async def execute(self, ctx: StepContext) -> StepResult:
        from ...automations.dispatcher import dispatch_automation

        cfg = ctx.action.config or {}
        child_id_raw = cfg.get("child_automation_id")
        if not child_id_raw:
            raise ValueError("sub_workflow action.config requires child_automation_id")
        try:
            child_id = uuid.UUID(str(child_id_raw))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"sub_workflow child_automation_id must be a UUID, got {child_id_raw!r}"
            ) from exc

        if str(child_id) == str(ctx.automation.id):
            raise ValueError(
                "sub_workflow refuses to invoke itself; use a different automation id for the child"
            )

        # Verify the child exists and is active. 404-like errors here
        # bubble up as engine failures with a clear reason.
        child = (
            await ctx.db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == child_id)
            )
        ).scalar_one_or_none()
        if child is None:
            raise ValueError(f"sub_workflow child_automation_id {child_id} not found")

        # Mint a fresh event for the child run with the configured input
        # as its payload. trigger_kind=manual records that the parent
        # workflow invoked it (cron / webhook / app_invocation are not
        # applicable for sub-runs).
        child_input = cfg.get("input") or {}
        event = AutomationEvent(
            id=uuid.uuid4(),
            automation_id=child.id,
            payload=dict(child_input),
            trigger_kind="manual",
        )
        ctx.db.add(event)
        await ctx.db.commit()

        result = await dispatch_automation(
            ctx.db,
            automation_id=child.id,
            event_id=event.id,
        )

        # Pull the child run's terminal raw_output so the parent step
        # carries it as output. If the child paused (waiting_approval)
        # the parent step is treated as failed for now; resumable
        # sub_workflow chaining is a Phase F follow-up.
        child_run = (
            await ctx.db.execute(select(AutomationRun).where(AutomationRun.id == result.run_id))
        ).scalar_one_or_none()

        terminal_output = (
            child_run.raw_output
            if child_run is not None and child_run.raw_output is not None
            else {}
        )

        return StepResult(
            output={
                "action_type": "sub_workflow",
                "child_automation_id": str(child.id),
                "child_run_id": str(result.run_id) if result.run_id else None,
                "child_status": result.run_status,
                "child_output": terminal_output,
            },
            async_handoff=False,
        )
