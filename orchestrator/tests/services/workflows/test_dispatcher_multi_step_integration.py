"""Dispatcher → engine integration test.

Exercises the FULL path that production traffic takes for a multi-step
automation:

* ``dispatch_automation`` is called with a real ``AutomationRun`` to
  create / update.
* The dispatcher loads actions, allocates budget if needed, marks
  ``status='running'``.
* The dispatcher detects ``len(actions) > 1`` and delegates to
  :func:`engine.execute_workflow`.
* The engine walks both actions, persists step-run rows.
* The dispatcher's existing finalization marks the run ``succeeded``.

Replaces the legacy assertion that multi-action automations were
rejected outright (Phase 1 behavior). The Base.metadata.create_all
fixture sidesteps the unrelated migration 0089 SQLite batch issue.
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


@pytest.mark.asyncio
async def test_dispatcher_delegates_two_action_automation_to_engine(session_maker, monkeypatch):
    from app.models_automations import (
        AutomationRun,
        AutomationStepRun,
    )
    from app.services.automations.dispatcher import (
        DispatchStatus,
        dispatch_automation,
    )

    # The dispatcher's gateway.send path will try to acquire a redis
    # client. Force the no-Redis branch so we don't need a live Redis.
    async def _no_redis():
        return None

    monkeypatch.setattr(
        "app.services.cache_service.get_redis_client",
        _no_redis,
    )

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
        await db.commit()

    # The dispatcher uses its own session; we just hand it the ids.
    async with session_maker() as db:
        result = await dispatch_automation(
            db,
            automation_id=autom_id,
            event_id=event_id,
        )

    assert result.status == DispatchStatus.SUCCEEDED, (
        f"unexpected dispatch status; reason={result.reason!r}"
    )
    assert result.run_status == "succeeded"

    # Step runs persisted in ordinal order, both succeeded.
    async with session_maker() as db:
        run = (
            await db.execute(select(AutomationRun).where(AutomationRun.id == result.run_id))
        ).scalar_one()
        assert run.status == "succeeded"

        step_runs = (
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
        assert len(step_runs) == 2
        assert [s.ordinal for s in step_runs] == [0, 1]
        assert all(s.status == "succeeded" for s in step_runs)
        assert step_runs[0].output is not None
        assert step_runs[0].output["body"] == "step 0"
        assert step_runs[1].output["body"] == "step 1"


@pytest.mark.asyncio
async def test_dispatcher_keeps_single_step_on_legacy_path(session_maker, monkeypatch):
    """A single-action automation must NOT touch automation_step_runs.

    The legacy dispatcher path stays in charge for one-step automations
    so existing production workloads run unchanged. The engine is only
    invoked when there are more than one action.
    """
    from app.models_automations import AutomationStepRun
    from app.services.automations.dispatcher import (
        DispatchStatus,
        dispatch_automation,
    )

    async def _no_redis():
        return None

    monkeypatch.setattr(
        "app.services.cache_service.get_redis_client",
        _no_redis,
    )

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            config={"body": "single"},
            ordinal=0,
        )
        event_id = await seed_event(db, automation_id=autom_id)
        await db.commit()

    async with session_maker() as db:
        result = await dispatch_automation(
            db,
            automation_id=autom_id,
            event_id=event_id,
        )

    assert result.status == DispatchStatus.SUCCEEDED

    async with session_maker() as db:
        step_runs = (
            (
                await db.execute(
                    select(AutomationStepRun).where(
                        AutomationStepRun.automation_run_id == result.run_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert step_runs == []
