"""G1 (#469): WorkflowVersion snapshots.

Covers:

* snapshot_definition_to_version writes generation=1 on first call.
* Identical content is deduped (UNIQUE on automation_id + payload_sha256).
* A real change produces generation=2 with parent set to the previous head.
* ensure_head_version lazy-creates for pre-G1 definitions.
* The engine reads from the version snapshot when run.workflow_version_id
  is set (snapshot is authoritative for past runs).
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
async def test_snapshot_creates_generation_1(session_maker):
    from app.models_automations import AutomationDefinition
    from app.models_workflows import WorkflowVersion
    from app.services.workflows.versions import snapshot_definition_to_version

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
        await db.commit()

    async with session_maker() as db:
        autom = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == autom_id)
            )
        ).scalar_one()
        result = await snapshot_definition_to_version(db, definition=autom, actor_user_id=owner_id)
        await db.commit()

        assert result.inserted is True
        assert result.version.generation == 1
        assert result.version.parent_version_id is None
        assert autom.head_version_id == result.version.id

        # Verify in DB.
        versions = (
            (
                await db.execute(
                    select(WorkflowVersion).where(WorkflowVersion.automation_id == autom_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(versions) == 1


@pytest.mark.asyncio
async def test_snapshot_dedupes_identical_payload(session_maker):
    from app.models_automations import AutomationDefinition
    from app.models_workflows import WorkflowVersion
    from app.services.workflows.versions import snapshot_definition_to_version

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            config={"body": "x"},
            ordinal=0,
        )
        await db.commit()

    async with session_maker() as db:
        autom = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == autom_id)
            )
        ).scalar_one()
        first = await snapshot_definition_to_version(db, definition=autom, actor_user_id=owner_id)
        await db.commit()

        second = await snapshot_definition_to_version(db, definition=autom, actor_user_id=owner_id)
        await db.commit()

        assert first.inserted is True
        assert second.inserted is False
        assert second.version.id == first.version.id

        # Only one row in DB.
        count = len(
            (
                await db.execute(
                    select(WorkflowVersion).where(WorkflowVersion.automation_id == autom_id)
                )
            )
            .scalars()
            .all()
        )
        assert count == 1


@pytest.mark.asyncio
async def test_snapshot_creates_generation_2_on_change(session_maker):
    from app.models_automations import (
        AutomationAction,
        AutomationDefinition,
    )
    from app.services.workflows.versions import snapshot_definition_to_version

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            config={"body": "v1"},
            ordinal=0,
        )
        await db.commit()

    async with session_maker() as db:
        autom = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == autom_id)
            )
        ).scalar_one()
        v1 = await snapshot_definition_to_version(db, definition=autom, actor_user_id=owner_id)
        await db.commit()

    # Change the live action.
    async with session_maker() as db:
        action = (
            await db.execute(
                select(AutomationAction).where(AutomationAction.automation_id == autom_id)
            )
        ).scalar_one()
        action.config = {"body": "v2"}
        await db.commit()

    async with session_maker() as db:
        autom = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == autom_id)
            )
        ).scalar_one()
        v2 = await snapshot_definition_to_version(db, definition=autom, actor_user_id=owner_id)
        await db.commit()

        assert v2.inserted is True
        assert v2.version.generation == 2
        assert v2.version.parent_version_id == v1.version.id
        assert autom.head_version_id == v2.version.id


@pytest.mark.asyncio
async def test_ensure_head_version_lazy_bootstraps(session_maker):
    from app.models_automations import AutomationDefinition
    from app.services.workflows.versions import ensure_head_version

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            config={"body": "bootstrap"},
            ordinal=0,
        )
        await db.commit()

    async with session_maker() as db:
        autom = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == autom_id)
            )
        ).scalar_one()
        assert autom.head_version_id is None

        version = await ensure_head_version(db, definition=autom)
        await db.commit()

        assert version.generation == 1
        assert autom.head_version_id == version.id


@pytest.mark.asyncio
async def test_engine_reads_from_version_snapshot(session_maker):
    """The strongest invariant: when a run is bound to a version, the
    engine MUST execute from that snapshot — not from the (possibly
    changed) live action rows. We snapshot, mutate the live rows to
    something obviously different, then dispatch and assert we got the
    snapshot's content back.
    """
    from app.models_automations import (
        AutomationAction,
        AutomationDefinition,
        AutomationRun,
        AutomationStepRun,
    )
    from app.services.workflows.engine import execute_workflow
    from app.services.workflows.versions import snapshot_definition_to_version

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            config={"body": "SNAPSHOT BODY"},
            ordinal=0,
        )
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            config={"body": "SNAPSHOT BODY 2"},
            ordinal=1,
        )
        event_id = await seed_event(db, automation_id=autom_id)
        await db.commit()

    # Snapshot at this point.
    async with session_maker() as db:
        autom = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == autom_id)
            )
        ).scalar_one()
        snap = await snapshot_definition_to_version(db, definition=autom, actor_user_id=owner_id)
        version_id = snap.version.id
        await db.commit()

    # Mutate the live rows to something obviously different.
    async with session_maker() as db:
        for a in (
            (
                await db.execute(
                    select(AutomationAction).where(AutomationAction.automation_id == autom_id)
                )
            )
            .scalars()
            .all()
        ):
            a.config = {"body": "MUTATED LIVE"}
        await db.commit()

    # Create a version-bound run.
    async with session_maker() as db:
        run_id = await seed_run(db, automation_id=autom_id, event_id=event_id)
        run = (
            await db.execute(select(AutomationRun).where(AutomationRun.id == run_id))
        ).scalar_one()
        run.workflow_version_id = version_id
        await db.commit()

    # Execute. The engine MUST read from the snapshot, not the mutated
    # live rows.
    async with session_maker() as db:
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
            event_payload={},
            budget_allocation=None,
        )

        # Final step output reflects the SNAPSHOT body, not the
        # MUTATED LIVE body.
        assert result.get("body") == "SNAPSHOT BODY 2", (
            f"engine read from live rows instead of version snapshot: {result!r}"
        )

        # Step runs persisted with snapshot's bodies.
        steps = (
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
        assert len(steps) == 2
        assert steps[0].output["body"] == "SNAPSHOT BODY"
        assert steps[1].output["body"] == "SNAPSHOT BODY 2"
