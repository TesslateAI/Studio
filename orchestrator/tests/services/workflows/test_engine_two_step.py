"""End-to-end test: a 2-step workflow runs through the engine.

Both steps are ``gateway.send`` because that handler is fully
synchronous and returns a deterministic ``redis_unavailable`` result
when Redis is not present (desktop mode), so we don't need to stand up
Redis to exercise the engine.

Asserts:

* :func:`execute_workflow` returns the FINAL step's output dict.
* Two ``automation_step_runs`` rows are persisted, both ``succeeded``,
  in ordinal order.
* Each step row carries the action's kind and an output dict.
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
async def test_two_synchronous_gateway_send_steps_run_to_completion(session_maker):
    from app.models_automations import (
        AutomationDefinition,
        AutomationRun,
        AutomationStepRun,
    )
    from app.services.workflows.engine import execute_workflow

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            config={"body": "hello from step 1"},
            ordinal=0,
        )
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            config={"body": "hello from step 2"},
            ordinal=1,
        )
        event_id = await seed_event(db, automation_id=autom_id, payload={"trigger": "manual"})
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

        result = await execute_workflow(
            db,
            run=run,
            automation=autom,
            event_payload={"trigger": "manual"},
            budget_allocation=None,
        )

        # Final step's output is what the dispatcher will hand to delivery.
        assert result["action_type"] == "gateway.send"
        assert result["body"] == "hello from step 2"

        # Two step-run rows persisted, in ordinal order, both succeeded.
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
        assert len(step_runs) == 2
        assert [s.ordinal for s in step_runs] == [0, 1]
        assert all(s.status == "succeeded" for s in step_runs)
        assert all(s.kind == "gateway.send" for s in step_runs)
        assert step_runs[0].output["body"] == "hello from step 1"
        assert step_runs[1].output["body"] == "hello from step 2"
        assert all(s.started_at is not None for s in step_runs)
        assert all(s.ended_at is not None for s in step_runs)


@pytest.mark.asyncio
async def test_engine_refuses_single_step_automation(session_maker):
    """The engine should not be invoked for single-step automations.

    The dispatcher routes single-action automations through the legacy
    path; calling the engine directly with one step is a programmer
    error and must surface as a clear exception.
    """
    from app.models_automations import AutomationDefinition, AutomationRun
    from app.services.workflows.engine import (
        WorkflowEngineError,
        execute_workflow,
    )

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            config={},
            ordinal=0,
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

        with pytest.raises(WorkflowEngineError, match="single-action"):
            await execute_workflow(
                db,
                run=run,
                automation=autom,
                event_payload={},
                budget_allocation=None,
            )
