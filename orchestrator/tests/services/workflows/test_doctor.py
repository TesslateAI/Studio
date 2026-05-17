"""G5 (#469): per-workflow doctor + workflow_event trigger adapter.

Covers:

* ensure_doctor_for creates a doctor row with workflow_event trigger
  pointing at the target.
* Re-calling ensure_doctor_for is idempotent (returns the same row).
* disable_doctor_for flips the flag + deactivates the trigger.
* route_workflow_event matches subscribers and fires AutomationEvent.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from .conftest import (
    seed_automation,
    seed_user,
)


@pytest.mark.asyncio
async def test_ensure_doctor_for_creates_doctor_and_trigger(session_maker):
    from app.models_automations import (
        AutomationAction,
        AutomationDefinition,
        AutomationTrigger,
    )
    from app.services.workflows.doctor import ensure_doctor_for

    async with session_maker() as db:
        owner_id = await seed_user(db)
        target_id = await seed_automation(db, owner_user_id=owner_id)
        await db.commit()

    async with session_maker() as db:
        target = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == target_id)
            )
        ).scalar_one()
        doctor = await ensure_doctor_for(db, target_automation=target)
        await db.commit()

        assert doctor.parent_automation_id == target_id
        assert doctor.depth == 1
        assert doctor.compute_profile == "connector_only"
        assert target.doctor_automation_id == doctor.id
        assert target.doctor_enabled is True

        # Doctor has a workflow_event trigger pointing at the target.
        trig = (
            await db.execute(
                select(AutomationTrigger).where(AutomationTrigger.automation_id == doctor.id)
            )
        ).scalar_one()
        assert trig.kind == "workflow_event"
        assert str(trig.config.get("watched_automation_id")) == str(target_id)

        # And exactly one action: agent.run.
        action = (
            await db.execute(
                select(AutomationAction).where(AutomationAction.automation_id == doctor.id)
            )
        ).scalar_one()
        assert action.action_type == "agent.run"


@pytest.mark.asyncio
async def test_ensure_doctor_for_idempotent(session_maker):
    from app.models_automations import AutomationDefinition
    from app.services.workflows.doctor import ensure_doctor_for

    async with session_maker() as db:
        owner_id = await seed_user(db)
        target_id = await seed_automation(db, owner_user_id=owner_id)
        await db.commit()

    async with session_maker() as db:
        target = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == target_id)
            )
        ).scalar_one()
        d1 = await ensure_doctor_for(db, target_automation=target)
        await db.commit()

    async with session_maker() as db:
        target = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == target_id)
            )
        ).scalar_one()
        d2 = await ensure_doctor_for(db, target_automation=target)
        await db.commit()
        assert d2.id == d1.id


@pytest.mark.asyncio
async def test_route_workflow_event_fires_subscribers(session_maker):
    import uuid as _uuid

    from app.models_automations import (
        AutomationDefinition,
        AutomationEvent,
    )
    from app.services.triggers.workflow_event import route_workflow_event
    from app.services.workflows.doctor import ensure_doctor_for

    async with session_maker() as db:
        owner_id = await seed_user(db)
        target_id = await seed_automation(db, owner_user_id=owner_id)
        await db.commit()

    async with session_maker() as db:
        target = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == target_id)
            )
        ).scalar_one()
        await ensure_doctor_for(db, target_automation=target)
        await db.commit()

    # Fire an error event for the target. The doctor should pick it up.
    async with session_maker() as db:
        event_ids = await route_workflow_event(
            db,
            source_automation_id=target_id,
            source_run_id=_uuid.uuid4(),
            event_kind="error.raised",
            payload={"error_type": "RuntimeError", "message": "boom"},
        )
        await db.commit()
        assert len(event_ids) == 1

        evt = (
            await db.execute(select(AutomationEvent).where(AutomationEvent.id == event_ids[0]))
        ).scalar_one()
        assert evt.trigger_kind == "workflow_event"
        assert evt.payload.get("event_kind") == "error.raised"
        assert str(evt.payload.get("source_automation_id")) == str(target_id)


@pytest.mark.asyncio
async def test_disable_doctor_for_flips_flag(session_maker):
    from app.models_automations import (
        AutomationDefinition,
        AutomationTrigger,
    )
    from app.services.workflows.doctor import (
        disable_doctor_for,
        ensure_doctor_for,
    )

    async with session_maker() as db:
        owner_id = await seed_user(db)
        target_id = await seed_automation(db, owner_user_id=owner_id)
        await db.commit()

    async with session_maker() as db:
        target = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == target_id)
            )
        ).scalar_one()
        await ensure_doctor_for(db, target_automation=target)
        await db.commit()

    async with session_maker() as db:
        target = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == target_id)
            )
        ).scalar_one()
        await disable_doctor_for(db, target_automation=target)
        await db.commit()

        assert target.doctor_enabled is False
        # Trigger deactivated.
        trigs = (
            (
                await db.execute(
                    select(AutomationTrigger).where(
                        AutomationTrigger.automation_id == target.doctor_automation_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert all(t.is_active is False for t in trigs)
