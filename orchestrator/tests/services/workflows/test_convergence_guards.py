"""G7 (#469): convergence guards (cooldown + diff budget + reset).

Covers:

* Agent-authored proposal within cooldown is refused with a clear reason.
* Agent-authored proposal after cooldown passes the guard.
* Diff-budget exhaustion forces manual approval.
* Human approve resets diff_budget_consumed to 0.
* User-authored proposals (proposer_run_id is None) bypass the
  cooldown — humans aren't rate-limited.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from .conftest import (
    seed_action,
    seed_automation,
    seed_user,
)


def test_cooldown_blocks_rapid_agent_edits():
    from app.models_automations import AutomationDefinition
    from app.services.workflows.proposals import evaluate_for_auto_apply

    autom = AutomationDefinition(
        auto_apply_policy={"allowed_changes": ["actions"]},
        diff_budget_max=5,
        diff_budget_consumed=0,
        min_seconds_between_self_edits=3600,
        last_self_edit_at=datetime.now(tz=UTC) - timedelta(seconds=60),
    )
    ok, reason = evaluate_for_auto_apply(
        automation=autom,
        diff=[{"path": "actions[ordinal=0]", "op": "replace"}],
        risk_class="low",
        proposer_run_id=uuid.uuid4(),
    )
    assert ok is False
    assert "cooldown active" in (reason or "")


def test_cooldown_does_not_block_human_edits():
    """User-authored (proposer_run_id None) bypasses cooldown."""
    from app.models_automations import AutomationDefinition
    from app.services.workflows.proposals import evaluate_for_auto_apply

    autom = AutomationDefinition(
        auto_apply_policy={"allowed_changes": ["actions"]},
        diff_budget_max=5,
        diff_budget_consumed=0,
        min_seconds_between_self_edits=3600,
        last_self_edit_at=datetime.now(tz=UTC) - timedelta(seconds=60),
    )
    ok, reason = evaluate_for_auto_apply(
        automation=autom,
        diff=[{"path": "actions[ordinal=0]", "op": "replace"}],
        risk_class="low",
        proposer_run_id=None,  # human path
    )
    assert ok is True, f"human edit should bypass cooldown; reason={reason}"


def test_cooldown_passes_after_window():
    from app.models_automations import AutomationDefinition
    from app.services.workflows.proposals import evaluate_for_auto_apply

    autom = AutomationDefinition(
        auto_apply_policy={"allowed_changes": ["actions"]},
        diff_budget_max=5,
        diff_budget_consumed=0,
        min_seconds_between_self_edits=60,
        last_self_edit_at=datetime.now(tz=UTC) - timedelta(seconds=120),
    )
    ok, reason = evaluate_for_auto_apply(
        automation=autom,
        diff=[{"path": "actions[ordinal=0]", "op": "replace"}],
        risk_class="low",
        proposer_run_id=uuid.uuid4(),
    )
    assert ok is True, f"reason={reason}"


def test_diff_budget_exhaustion_forces_manual():
    from app.models_automations import AutomationDefinition
    from app.services.workflows.proposals import evaluate_for_auto_apply

    autom = AutomationDefinition(
        auto_apply_policy={"allowed_changes": ["actions"]},
        diff_budget_max=3,
        diff_budget_consumed=3,
        min_seconds_between_self_edits=0,
        last_self_edit_at=None,
    )
    ok, reason = evaluate_for_auto_apply(
        automation=autom,
        diff=[{"path": "actions[ordinal=0]"}],
        risk_class="low",
        proposer_run_id=uuid.uuid4(),
    )
    assert ok is False
    assert "diff budget exhausted" in (reason or "")


@pytest.mark.asyncio
async def test_human_approve_resets_diff_budget(session_maker):
    from app.models_automations import AutomationDefinition
    from app.services.workflows.proposals import (
        create_proposal,
        decide_proposal,
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
        autom.diff_budget_consumed = 3  # pretend agent already used 3
        await snapshot_definition_to_version(db, definition=autom, actor_user_id=owner_id)
        await db.commit()

    # Human submits + approves a proposal — budget should reset.
    async with session_maker() as db:
        autom = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == autom_id)
            )
        ).scalar_one()
        result = await create_proposal(
            db,
            automation=autom,
            to_payload={
                "actions": [
                    {
                        "ordinal": 0,
                        "action_type": "gateway.send",
                        "config": {"body": "human edit"},
                        "app_action_id": None,
                        "parent_action_id": None,
                        "branch_condition": None,
                    }
                ],
                "triggers": [],
                "delivery_targets": [],
            },
            rationale="human review",
            proposer_user_id=owner_id,
        )
        await db.commit()
        pid = result.proposal.id

    async with session_maker() as db:
        await decide_proposal(db, proposal_id=pid, decision="approve", reviewer_user_id=owner_id)
        await db.commit()

        autom = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == autom_id)
            )
        ).scalar_one()
        assert int(autom.diff_budget_consumed) == 0
