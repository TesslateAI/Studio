"""Phase C (#472): append-only run-event log.

Tests:

* The engine emits ``step.started`` + ``step.finished`` events around
  each step in a multi-step run (one of each per step, in order).
* Each event row carries the kind, actor, ordinal, and step kind in
  the payload.
* ``record`` swallows database errors (a write hiccup must not abort
  the run; the log is observability, not control plane).
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
async def test_engine_emits_step_lifecycle_events(session_maker):
    from app.models_automations import (
        AutomationDefinition,
        AutomationRun,
        AutomationRunEvent,
    )
    from app.services.workflows.engine import execute_workflow
    from app.services.workflows.event_log import EventKind

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
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
            action_type="gateway.send",
            config={"body": "step 1"},
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

        await execute_workflow(
            db,
            run=run,
            automation=autom,
            event_payload={},
            budget_allocation=None,
        )

        events = (
            (
                await db.execute(
                    select(AutomationRunEvent)
                    .where(AutomationRunEvent.automation_run_id == run_id)
                    .order_by(AutomationRunEvent.ts.asc())
                )
            )
            .scalars()
            .all()
        )
        kinds = [e.kind for e in events]
        # Each step contributes one started + one finished. Sequencing
        # should be: started(0) -> finished(0) -> started(1) -> finished(1).
        assert kinds == [
            EventKind.STEP_STARTED,
            EventKind.STEP_FINISHED,
            EventKind.STEP_STARTED,
            EventKind.STEP_FINISHED,
        ]
        # Payload + actor checks on the first started event.
        first = events[0]
        assert first.actor == "engine"
        assert first.payload.get("ordinal") == 0
        assert first.payload.get("step_kind") == "gateway.send"
        # Finished events record the status.
        finished_first = events[1]
        assert finished_first.payload.get("status") == "succeeded"


@pytest.mark.asyncio
async def test_engine_emits_failure_events_on_error(session_maker, monkeypatch):
    """Step failure -> step.finished(status=failed) + error.raised."""
    from app.models_automations import (
        AutomationDefinition,
        AutomationRun,
        AutomationRunEvent,
    )
    from app.services.workflows.engine import execute_workflow
    from app.services.workflows.event_log import EventKind

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated boom")

    monkeypatch.setattr(
        "app.services.automations.dispatcher._dispatch_gateway_send",
        _boom,
    )

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            ordinal=0,
        )
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
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

        with pytest.raises(RuntimeError):
            await execute_workflow(
                db,
                run=run,
                automation=autom,
                event_payload={},
                budget_allocation=None,
            )

        events = (
            (
                await db.execute(
                    select(AutomationRunEvent)
                    .where(AutomationRunEvent.automation_run_id == run_id)
                    .order_by(AutomationRunEvent.ts.asc())
                )
            )
            .scalars()
            .all()
        )
        kinds = [e.kind for e in events]
        assert EventKind.STEP_STARTED in kinds
        assert EventKind.STEP_FINISHED in kinds
        assert EventKind.ERROR_RAISED in kinds
        # The finished event for the failing step should record status=failed.
        finished = next(e for e in events if e.kind == EventKind.STEP_FINISHED)
        assert finished.payload.get("status") == "failed"
        # No second step started since the engine bailed.
        assert kinds.count(EventKind.STEP_STARTED) == 1


@pytest.mark.asyncio
async def test_record_swallows_db_errors(monkeypatch):
    """A failed insert must not raise out of record() — observability != control."""
    from app.services.workflows import event_log

    class FakeSession:
        async def commit(self):
            raise RuntimeError("db down")

        async def rollback(self):
            return None

        def add(self, _):
            return None

    # Should NOT raise.
    await event_log.record(
        FakeSession(),  # type: ignore[arg-type]
        run_id="x",
        kind=event_log.EventKind.STEP_STARTED,
        actor="engine",
        payload={"ordinal": 0},
    )
