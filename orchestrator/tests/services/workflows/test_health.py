"""G4 (#469): WorkflowHealthSnapshot.

Covers:

* compute_snapshot writes a new snapshot for (automation, window)
  with success_rate / failure_count / open_proposal_count from real
  rows.
* Re-running compute_snapshot upserts in place (one row per
  automation+window).
* success_rate is None when no terminal runs exist yet (so the
  doctor doesn't treat "0 runs" as "100% failure").
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from .conftest import (
    seed_action,
    seed_automation,
    seed_event,
    seed_user,
)


async def _seed_run(db, *, automation_id, event_id, status, started=None, ended=None):
    from app.models_automations import AutomationRun

    run = AutomationRun(
        id=uuid.uuid4(),
        automation_id=automation_id,
        event_id=event_id,
        status=status,
        started_at=started or datetime.now(tz=UTC),
        ended_at=ended,
    )
    db.add(run)
    await db.flush()
    return run.id


@pytest.mark.asyncio
async def test_compute_snapshot_with_no_runs(session_maker):
    from app.models_workflows import WorkflowHealthSnapshot
    from app.services.workflows.health import compute_snapshot

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            ordinal=0,
        )
        await db.commit()

    async with session_maker() as db:
        snap = await compute_snapshot(db, automation_id=autom_id, window="short")
        await db.commit()

        assert snap.run_count == 0
        assert snap.success_count == 0
        assert snap.failure_count == 0
        # No terminal runs -> None, not 0.0 (the "no signal" sentinel).
        assert snap.success_rate is None

        # One row in DB.
        rows = (
            (
                await db.execute(
                    select(WorkflowHealthSnapshot).where(
                        WorkflowHealthSnapshot.automation_id == autom_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_compute_snapshot_with_mixed_outcomes(session_maker):
    from app.services.workflows.health import compute_snapshot

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            ordinal=0,
        )
        # 3 successes + 1 failure = 75% success rate.
        for _ in range(3):
            event_id = await seed_event(db, automation_id=autom_id)
            await _seed_run(
                db,
                automation_id=autom_id,
                event_id=event_id,
                status="succeeded",
                ended=datetime.now(tz=UTC),
            )
        event_id = await seed_event(db, automation_id=autom_id)
        await _seed_run(
            db,
            automation_id=autom_id,
            event_id=event_id,
            status="failed",
            ended=datetime.now(tz=UTC),
        )
        await db.commit()

    async with session_maker() as db:
        snap = await compute_snapshot(db, automation_id=autom_id, window="short")
        await db.commit()

        assert snap.run_count == 4
        assert snap.success_count == 3
        assert snap.failure_count == 1
        assert snap.success_rate is not None
        assert abs(float(snap.success_rate) - 0.75) < 0.001
        assert snap.last_failed_run_id is not None


@pytest.mark.asyncio
async def test_compute_snapshot_upserts_in_place(session_maker):
    from app.models_workflows import WorkflowHealthSnapshot
    from app.services.workflows.health import compute_snapshot

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            ordinal=0,
        )
        await db.commit()

    async with session_maker() as db:
        first = await compute_snapshot(db, automation_id=autom_id, window="short")
        first_id = first.id
        await db.commit()

    # Add a run.
    async with session_maker() as db:
        event_id = await seed_event(db, automation_id=autom_id)
        await _seed_run(
            db,
            automation_id=autom_id,
            event_id=event_id,
            status="succeeded",
            ended=datetime.now(tz=UTC),
        )
        await db.commit()

    async with session_maker() as db:
        second = await compute_snapshot(db, automation_id=autom_id, window="short")
        await db.commit()

        # Same row, updated metrics.
        assert second.id == first_id
        assert second.run_count == 1
        assert second.success_count == 1

        # Still only one row in DB.
        rows = (
            (
                await db.execute(
                    select(WorkflowHealthSnapshot).where(
                        WorkflowHealthSnapshot.automation_id == autom_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
