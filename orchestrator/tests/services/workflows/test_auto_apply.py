"""G3 (#469): auto_apply_policy + dry_run.

Covers:

* evaluate_for_auto_apply returns False when no policy is set.
* evaluate_for_auto_apply returns False when risk_class=high.
* evaluate_for_auto_apply respects allowed_changes + hard_blocked +
  max_changes_per_proposal.
* evaluate_dry_run short-circuits gateway.send/deliver/branch/sub_workflow
  cleanly.
* evaluate_dry_run refuses agent.run + app.invoke with a clear reason.
* End-to-end: create_proposal against an automation with auto_apply_policy
  auto-applies a low-risk change (gateway body) and bumps
  diff_budget_consumed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from .conftest import (
    seed_action,
    seed_automation,
    seed_user,
)


def test_evaluate_dry_run_short_circuits_basic_kinds():
    from app.services.workflows.dry_run import evaluate_dry_run

    payload = {
        "actions": [
            {"ordinal": 0, "action_type": "gateway.send", "config": {"body": "hi"}},
            {"ordinal": 1, "action_type": "branch", "config": {}},
            {"ordinal": 2, "action_type": "deliver", "config": {}},
            {
                "ordinal": 3,
                "action_type": "sub_workflow",
                "config": {"child_automation_id": "00000000-0000-0000-0000-000000000001"},
            },
        ]
    }
    result = evaluate_dry_run(payload)
    assert result.ok is True
    assert len(result.steps) == 4
    assert all(s.ok for s in result.steps)


def test_evaluate_dry_run_refuses_agent_run():
    from app.services.workflows.dry_run import evaluate_dry_run

    payload = {
        "actions": [
            {"ordinal": 0, "action_type": "gateway.send", "config": {"body": "ok"}},
            {"ordinal": 1, "action_type": "agent.run", "config": {}},
        ]
    }
    result = evaluate_dry_run(payload)
    assert result.ok is False
    assert "agent.run" in (result.refusal_reason or "")


def test_evaluate_dry_run_refuses_app_invoke():
    from app.services.workflows.dry_run import evaluate_dry_run

    payload = {
        "actions": [
            {"ordinal": 0, "action_type": "app.invoke", "config": {}},
        ]
    }
    result = evaluate_dry_run(payload)
    assert result.ok is False
    assert "app.invoke" in (result.refusal_reason or "")


def test_evaluate_for_auto_apply_no_policy():
    from app.models_automations import AutomationDefinition
    from app.services.workflows.proposals import evaluate_for_auto_apply

    autom = AutomationDefinition(auto_apply_policy=None)
    ok, reason = evaluate_for_auto_apply(
        automation=autom, diff=[{"path": "x", "op": "replace"}], risk_class="low"
    )
    assert ok is False
    assert "no auto_apply_policy" in (reason or "")


def test_evaluate_for_auto_apply_high_risk_blocked():
    from app.models_automations import AutomationDefinition
    from app.services.workflows.proposals import evaluate_for_auto_apply

    autom = AutomationDefinition(auto_apply_policy={"allowed_changes": ["actions"]})
    ok, reason = evaluate_for_auto_apply(
        automation=autom, diff=[{"path": "actions[ordinal=0]"}], risk_class="high"
    )
    assert ok is False
    assert "risk_class=high" in (reason or "")


def test_evaluate_for_auto_apply_path_not_allowed():
    from app.models_automations import AutomationDefinition
    from app.services.workflows.proposals import evaluate_for_auto_apply

    autom = AutomationDefinition(auto_apply_policy={"allowed_changes": ["actions"]})
    ok, reason = evaluate_for_auto_apply(
        automation=autom,
        diff=[{"path": "contract", "op": "replace"}],
        risk_class="low",
    )
    assert ok is False
    assert "contract" in (reason or "")


def test_evaluate_for_auto_apply_passes_when_paths_match():
    from app.models_automations import AutomationDefinition
    from app.services.workflows.proposals import evaluate_for_auto_apply

    autom = AutomationDefinition(
        auto_apply_policy={
            "allowed_changes": ["actions"],
            "max_changes_per_proposal": 5,
        }
    )
    ok, reason = evaluate_for_auto_apply(
        automation=autom,
        diff=[
            {"path": "actions[ordinal=0]", "op": "replace"},
            {"path": "actions[ordinal=1]", "op": "replace"},
        ],
        risk_class="low",
    )
    assert ok is True
    assert reason is None


def test_evaluate_for_auto_apply_hard_blocked():
    from app.models_automations import AutomationDefinition
    from app.services.workflows.proposals import evaluate_for_auto_apply

    autom = AutomationDefinition(
        auto_apply_policy={
            "allowed_changes": ["actions"],
            "hard_blocked": ["actions[ordinal=0]"],
        }
    )
    ok, reason = evaluate_for_auto_apply(
        automation=autom,
        diff=[{"path": "actions[ordinal=0]"}],
        risk_class="low",
    )
    assert ok is False
    assert "hard-blocked" in (reason or "")


@pytest.mark.asyncio
async def test_auto_apply_end_to_end_changes_live_row(session_maker):
    from app.models_automations import (
        AutomationAction,
        AutomationDefinition,
    )
    from app.services.workflows.proposals import create_proposal
    from app.services.workflows.versions import snapshot_definition_to_version

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            config={"body": "ORIGINAL"},
            ordinal=0,
        )
        await db.commit()

    # Set the auto_apply_policy on the definition.
    async with session_maker() as db:
        autom = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == autom_id)
            )
        ).scalar_one()
        autom.auto_apply_policy = {
            "allowed_changes": ["actions"],
            "max_changes_per_proposal": 5,
        }
        await snapshot_definition_to_version(db, definition=autom, actor_user_id=owner_id)
        await db.commit()

    async with session_maker() as db:
        autom = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == autom_id)
            )
        ).scalar_one()
        before_budget = int(autom.diff_budget_consumed or 0)
        result = await create_proposal(
            db,
            automation=autom,
            to_payload={
                "actions": [
                    {
                        "ordinal": 0,
                        "action_type": "gateway.send",
                        "config": {"body": "AUTO-APPLIED"},
                        "app_action_id": None,
                        "parent_action_id": None,
                        "branch_condition": None,
                    }
                ],
                "triggers": [],
                "delivery_targets": [],
            },
            rationale="adjust body",
            risk_class="low",
            proposer_user_id=owner_id,
        )
        await db.commit()

        assert result.proposal.status == "applied"
        assert result.proposal.applied_version_id is not None

    # Live row reflects the auto-applied change.
    async with session_maker() as db:
        action = (
            await db.execute(
                select(AutomationAction).where(AutomationAction.automation_id == autom_id)
            )
        ).scalar_one()
        assert action.config["body"] == "AUTO-APPLIED"

        autom = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == autom_id)
            )
        ).scalar_one()
        assert int(autom.diff_budget_consumed) == before_budget + 1
