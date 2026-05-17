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
        from sqlalchemy.ext.asyncio import async_sessionmaker

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

        # Verify the child exists (read-only on the parent session — safe).
        child = (
            await ctx.db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == child_id)
            )
        ).scalar_one_or_none()
        if child is None:
            raise ValueError(f"sub_workflow child_automation_id {child_id} not found")

        # Isolate the child invocation in a fresh DB session. The child's
        # dispatcher runs the full pipeline (preflight → step rows →
        # event commits → finalize), each of which commits on its own.
        # Sharing ``ctx.db`` would interleave those commits with the
        # parent step row writes in ``engine.py`` and corrupt the parent's
        # transaction boundaries — most visibly on child failure where
        # the parent's exception handler would operate on a session whose
        # state was mutated by N child commits/rollbacks.
        child_input = cfg.get("input") or {}
        child_run_id = None
        child_run_status = None
        terminal_output: dict = {}

        # Build a fresh session bound to the same async engine as the
        # parent. Reusing the engine (not the session) keeps the parent's
        # transaction isolated from the child's commits while staying
        # within whichever DB the test harness or runtime is wired to
        # (SQLite for unit tests, Postgres in deploy). ``ctx.db.bind``
        # returns the AsyncEngine directly; ``get_bind()`` unwraps to
        # the sync proxy which async_sessionmaker rejects.
        parent_engine = ctx.db.bind
        ChildSession = async_sessionmaker(parent_engine, expire_on_commit=False)

        async with ChildSession() as child_db:
            event = AutomationEvent(
                id=uuid.uuid4(),
                automation_id=child.id,
                payload=dict(child_input),
                trigger_kind="manual",
            )
            child_db.add(event)
            await child_db.commit()

            result = await dispatch_automation(
                child_db,
                automation_id=child.id,
                event_id=event.id,
            )
            child_run_id = result.run_id
            child_run_status = result.run_status

            child_run = (
                await child_db.execute(
                    select(AutomationRun).where(AutomationRun.id == result.run_id)
                )
            ).scalar_one_or_none()
            if child_run is not None and child_run.raw_output is not None:
                terminal_output = child_run.raw_output

        return StepResult(
            output={
                "action_type": "sub_workflow",
                "child_automation_id": str(child.id),
                "child_run_id": str(child_run_id) if child_run_id else None,
                "child_status": child_run_status,
                "child_output": terminal_output,
            },
            async_handoff=False,
        )
