"""Phase F (#475): branch + sub_workflow step kinds.

Covers:

* ``branch`` with kind=equals, true path takes then_ordinal, false path
  takes else_ordinal. Ordinals between current and target are skipped
  cleanly without firing their handlers.
* ``sub_workflow`` invokes a child automation and captures its
  terminal output as the parent step's output.
* The handler refuses self-invocation (defense-in-depth against the
  existing parent_automation_id chain check).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from .conftest import (
    seed_action,
    seed_automation,
    seed_event,
    seed_user,
)


def test_phase_f_handlers_register():
    import app.services.workflows.handlers  # noqa: F401
    from app.services.workflows.handlers.base import known_kinds

    kinds = known_kinds()
    assert "branch" in kinds
    assert "sub_workflow" in kinds


@pytest.mark.asyncio
async def test_branch_taken_skips_intermediate_steps(session_maker):
    from app.models_automations import AutomationStepRun
    from app.services.automations.dispatcher import dispatch_automation

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        # 4-step graph:
        #   ordinal 0: gateway.send (always runs)
        #   ordinal 1: branch with then_ordinal=3 (skip 2)
        #   ordinal 2: gateway.send (skipped on true)
        #   ordinal 3: gateway.send (taken on true)
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            config={"body": "step 0"},
            ordinal=0,
        )
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="branch",
            config={
                "condition": {
                    "kind": "equals",
                    "left": "{step.body}",
                    "right": "step 0",
                },
                "then_ordinal": 3,
                "else_ordinal": 2,
            },
            ordinal=1,
        )
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            config={"body": "step 2 (should be skipped)"},
            ordinal=2,
        )
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            config={"body": "step 3 (target)"},
            ordinal=3,
        )
        event_id = await seed_event(db, automation_id=autom_id)
        await db.commit()

    async with session_maker() as db:
        result = await dispatch_automation(db, automation_id=autom_id, event_id=event_id)
        assert str(result.status) == "succeeded"

    async with session_maker() as db:
        steps = (
            (
                await db.execute(
                    select(AutomationStepRun)
                    .where(AutomationStepRun.automation_run_id == result.run_id)
                    .order_by(AutomationStepRun.ordinal.asc())
                )
            )
            .scalars()
            .all()
        )
        ordinals_run = [s.ordinal for s in steps]
        # Branch took step 0 -> branch -> step 3, skipping step 2.
        assert 0 in ordinals_run
        assert 1 in ordinals_run
        assert 2 not in ordinals_run
        assert 3 in ordinals_run


@pytest.mark.asyncio
async def test_sub_workflow_invokes_child_synchronously(session_maker):
    from app.models_automations import AutomationRun
    from app.services.automations.dispatcher import dispatch_automation

    async with session_maker() as db:
        owner_id = await seed_user(db)

        # Child: a simple two-step sequence so the engine path exercises.
        child_id = await seed_automation(db, owner_user_id=owner_id)
        await seed_action(
            db,
            automation_id=child_id,
            action_type="gateway.send",
            config={"body": "child step a"},
            ordinal=0,
        )
        await seed_action(
            db,
            automation_id=child_id,
            action_type="gateway.send",
            config={"body": "child step b"},
            ordinal=1,
        )

        # Parent: gateway.send -> sub_workflow(child).
        parent_id = await seed_automation(db, owner_user_id=owner_id)
        await seed_action(
            db,
            automation_id=parent_id,
            action_type="gateway.send",
            config={"body": "parent first"},
            ordinal=0,
        )
        await seed_action(
            db,
            automation_id=parent_id,
            action_type="sub_workflow",
            config={"child_automation_id": str(child_id)},
            ordinal=1,
        )
        event_id = await seed_event(db, automation_id=parent_id)
        await db.commit()

    async with session_maker() as db:
        result = await dispatch_automation(db, automation_id=parent_id, event_id=event_id)
        assert str(result.status) == "succeeded"

    # The child has its own AutomationRun row.
    async with session_maker() as db:
        child_runs = (
            (await db.execute(select(AutomationRun).where(AutomationRun.automation_id == child_id)))
            .scalars()
            .all()
        )
        assert len(child_runs) == 1
        assert child_runs[0].status == "succeeded"


@pytest.mark.asyncio
async def test_sub_workflow_refuses_self_invocation(session_maker):
    from app.services.automations.dispatcher import dispatch_automation

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            config={"body": "first"},
            ordinal=0,
        )
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="sub_workflow",
            config={"child_automation_id": str(autom_id)},
            ordinal=1,
        )
        event_id = await seed_event(db, automation_id=autom_id)
        await db.commit()

    async with session_maker() as db:
        result = await dispatch_automation(db, automation_id=autom_id, event_id=event_id)
        # The handler raises ValueError on self-invoke; the dispatcher
        # captures it as a run failure.
        assert str(result.status) == "failed"
        assert "sub_workflow" in (result.reason or "") or "invoke" in (result.reason or "")
