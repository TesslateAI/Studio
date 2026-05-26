"""G6 (#469): WorkflowLearning record + lookup + outcome tracking."""

from __future__ import annotations

import uuid

import pytest

from .conftest import seed_user


@pytest.mark.asyncio
async def test_record_and_lookup_learning(session_maker):
    from app.services.workflows.learnings import (
        lookup_learnings,
        record_learning,
        record_outcome,
    )

    async with session_maker() as db:
        await seed_user(db)
        await db.commit()

    async with session_maker() as db:
        l1 = await record_learning(
            db,
            team_id=None,
            tag="deliver.slack.timeout",
            symptom_pattern={"step_kind": "deliver", "error_kw": ["timeout"]},
            proposed_fix={"actions": [{"config": {"timeout_seconds": 30}}]},
            created_by_run_id=uuid.uuid4(),
        )
        await db.commit()
        # Record some successes.
        await record_outcome(db, learning_id=l1.id, outcome="success")
        await record_outcome(db, learning_id=l1.id, outcome="success")
        await record_outcome(db, learning_id=l1.id, outcome="failure")
        await db.commit()

    async with session_maker() as db:
        rows = await lookup_learnings(db, team_id=None, tag_prefix="deliver.")
        assert len(rows) == 1
        assert rows[0].success_count == 2
        assert rows[0].failure_count == 1
        assert rows[0].tag == "deliver.slack.timeout"


@pytest.mark.asyncio
async def test_lookup_ranks_by_success_rate(session_maker):
    from app.services.workflows.learnings import (
        lookup_learnings,
        record_learning,
        record_outcome,
    )

    async with session_maker() as db:
        await seed_user(db)
        await db.commit()

    async with session_maker() as db:
        good = await record_learning(
            db,
            team_id=None,
            tag="deliver.a",
            symptom_pattern={},
            proposed_fix={},
            created_by_run_id=None,
        )
        bad = await record_learning(
            db,
            team_id=None,
            tag="deliver.b",
            symptom_pattern={},
            proposed_fix={},
            created_by_run_id=None,
        )
        await db.commit()
        # good: 4/5 success, bad: 1/5.
        for _ in range(4):
            await record_outcome(db, learning_id=good.id, outcome="success")
        await record_outcome(db, learning_id=good.id, outcome="failure")
        await record_outcome(db, learning_id=bad.id, outcome="success")
        for _ in range(4):
            await record_outcome(db, learning_id=bad.id, outcome="failure")
        await db.commit()

    async with session_maker() as db:
        rows = await lookup_learnings(db, team_id=None, tag_prefix="deliver.")
        assert len(rows) == 2
        # Higher-success-rate learning ranks first.
        assert rows[0].id == good.id
        assert rows[1].id == bad.id
