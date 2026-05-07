"""Phase A constraint: a multi-step workflow cannot contain an async step.

Tier-0 ``agent.run`` returns ``{"enqueued": True}`` because the actual
LLM loop runs in the worker. Until Phase B wires the worker callback
back into the engine, chaining a next step after that handoff would
silently drop work. The engine must reject the multi-step workflow
loudly with :class:`AsyncStepInMultiStepError` and mark the failing
step run as ``failed``.

We monkey-patch the agent.run handler to simulate the async handoff
return shape so the test does not stand up the real ARQ task queue.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from .conftest import (
    seed_action,
    seed_automation,
    seed_event,
    seed_run,
    seed_user,
)


@pytest.mark.asyncio
async def test_async_handoff_in_multi_step_is_rejected(session_maker, monkeypatch):
    from app.models_automations import (
        AutomationDefinition,
        AutomationRun,
        AutomationStepRun,
    )
    from app.services.workflows.engine import (
        AsyncStepInMultiStepError,
        execute_workflow,
    )
    from app.services.workflows.handlers import agent_turn

    async def _fake_agent_run(*args, **kwargs):
        return {"enqueued": True, "task_id": "fake-arq-task"}

    # Patch the dispatcher-side function the agent.run handler calls.
    monkeypatch.setattr(
        "app.services.automations.dispatcher._dispatch_agent_run",
        _fake_agent_run,
    )

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        # tier=0 -> tier-0 agent.run path -> returns enqueued=True.
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="agent.run",
            ordinal=0,
        )
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            config={"body": "step 2"},
            ordinal=1,
        )
        event_id = await seed_event(db, automation_id=autom_id)
        run_id = await seed_run(db, automation_id=autom_id, event_id=event_id)
        await db.commit()

        autom = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == autom_id)
            )
        ).scalar_one()
        run = (
            await db.execute(select(AutomationRun).where(AutomationRun.id == run_id))
        ).scalar_one()

        # Sanity: handler exists and is wired to the patched function.
        assert agent_turn.AgentTurnHandler.kind == "agent.run"

        with pytest.raises(AsyncStepInMultiStepError):
            await execute_workflow(
                db,
                run=run,
                automation=autom,
                event_payload={},
                budget_allocation=None,
            )

        # The first step row must be marked failed with the diagnostic
        # message; the second step must NOT have been started.
        step_runs = (
            (
                await db.execute(
                    select(AutomationStepRun)
                    .where(AutomationStepRun.automation_run_id == run_id)
                    .order_by(AutomationStepRun.ordinal.asc())
                )
            )
            .scalars()
            .all()
        )
        assert len(step_runs) == 1
        assert step_runs[0].kind == "agent.run"
        assert step_runs[0].status == "failed"
        assert step_runs[0].error is not None
        assert "async-handoff" in step_runs[0].error
