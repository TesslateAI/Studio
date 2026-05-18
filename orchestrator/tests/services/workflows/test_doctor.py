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
    seed_marketplace_agent,
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
        await seed_marketplace_agent(db)
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
        # TC-03 compat: agent.run config carries a real agent_id so the
        # response projection's Pydantic validator (require config.agent_id
        # to be a UUID string) is satisfied. Without this, GET on the
        # doctor would 500.
        cfg = action.config or {}
        assert cfg.get("agent_id"), "doctor agent.run must carry agent_id"
        from uuid import UUID as _UUID

        _UUID(str(cfg["agent_id"]))  # parses


@pytest.mark.asyncio
async def test_ensure_doctor_for_raises_without_agent_in_library(session_maker):
    """No system agent + no library agent → clear error at enable time
    instead of a deferred 500 on first detail GET."""
    from app.models_automations import AutomationDefinition
    from app.services.workflows.doctor import DoctorNoAgentAvailable, ensure_doctor_for

    async with session_maker() as db:
        owner_id = await seed_user(db)
        target_id = await seed_automation(db, owner_user_id=owner_id)
        # NB: deliberately NO seed_marketplace_agent call.
        await db.commit()

    async with session_maker() as db:
        target = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == target_id)
            )
        ).scalar_one()
        with pytest.raises(DoctorNoAgentAvailable):
            await ensure_doctor_for(db, target_automation=target)


@pytest.mark.asyncio
async def test_ensure_doctor_for_idempotent(session_maker):
    from app.models_automations import AutomationDefinition
    from app.services.workflows.doctor import ensure_doctor_for

    async with session_maker() as db:
        owner_id = await seed_user(db)
        await seed_marketplace_agent(db)
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
        await seed_marketplace_agent(db)
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
        await seed_marketplace_agent(db)
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


@pytest.mark.asyncio
async def test_emit_run_finished_fires_doctor_on_run_failed(session_maker):
    """G5 #469 blocker: doctor must fire on terminal run.failed, not
    just per-step error.raised. The synthetic run.failed workflow_event
    emission lives in services.workflows.event_log.emit_run_finished.
    """
    from app.models_automations import AutomationDefinition, AutomationEvent
    from app.services.workflows.doctor import ensure_doctor_for
    from app.services.workflows.event_log import emit_run_finished

    async with session_maker() as db:
        owner_id = await seed_user(db)
        await seed_marketplace_agent(db)
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

    # Fire emit_run_finished with status=failed. The doctor's
    # workflow_event trigger subscribes to "run.failed" so it should
    # mint an AutomationEvent on the doctor automation.
    import uuid as _uuid

    async with session_maker() as db:
        await emit_run_finished(
            db,
            run_id=_uuid.uuid4(),
            automation_id=target_id,
            status="failed",
            reason="boom",
        )
        await db.commit()

        # The doctor automation should have an AutomationEvent waiting.
        target_after = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == target_id)
            )
        ).scalar_one()
        doctor_id = target_after.doctor_automation_id
        assert doctor_id is not None

        events = (
            (
                await db.execute(
                    select(AutomationEvent).where(AutomationEvent.automation_id == doctor_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1
        assert events[0].payload.get("event_kind") == "run.failed"
        assert events[0].payload.get("event_payload", {}).get("status") == "failed"
        assert events[0].payload.get("event_payload", {}).get("reason") == "boom"


@pytest.mark.asyncio
async def test_emit_run_finished_skips_fan_out_on_success(session_maker):
    """Success runs record run.finished but don't fire doctors —
    otherwise every healthy run would page the doctor."""
    from app.models_automations import AutomationDefinition, AutomationEvent
    from app.services.workflows.doctor import ensure_doctor_for
    from app.services.workflows.event_log import emit_run_finished

    async with session_maker() as db:
        owner_id = await seed_user(db)
        await seed_marketplace_agent(db)
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

    import uuid as _uuid

    async with session_maker() as db:
        await emit_run_finished(
            db,
            run_id=_uuid.uuid4(),
            automation_id=target_id,
            status="succeeded",
        )
        await db.commit()

        target_after = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == target_id)
            )
        ).scalar_one()
        doctor_id = target_after.doctor_automation_id
        events = (
            (
                await db.execute(
                    select(AutomationEvent).where(AutomationEvent.automation_id == doctor_id)
                )
            )
            .scalars()
            .all()
        )
        assert events == []
