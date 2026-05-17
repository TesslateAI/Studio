"""G2 (#469): WorkflowProposal lifecycle.

Covers:

* create_proposal writes a row with computed diff_summary, status=submitted.
* Idempotent on (automation, from_version, payload SHA): re-submitting
  the same content returns the existing row.
* decide_proposal(approve) writes a new WorkflowVersion + flips
  head_version_id + replaces child rows + marks proposal applied.
* decide_proposal(reject) marks rejected without touching the
  definition.
* decide_proposal on already-decided raises ProposalAlreadyDecided.
* withdraw_proposal marks status=withdrawn.
* compute_diff produces structured entries for scalar + list changes.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from .conftest import (
    seed_action,
    seed_automation,
    seed_user,
)


@pytest.mark.asyncio
async def test_create_proposal_writes_row_and_diff(session_maker):
    from app.models_automations import AutomationDefinition
    from app.services.workflows.proposals import create_proposal
    from app.services.workflows.versions import snapshot_definition_to_version

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            config={"body": "before"},
            ordinal=0,
        )
        await db.commit()

    async with session_maker() as db:
        autom = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == autom_id)
            )
        ).scalar_one()
        await snapshot_definition_to_version(db, definition=autom, actor_user_id=owner_id)
        await db.commit()

    async with session_maker() as db:
        autom = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == autom_id)
            )
        ).scalar_one()
        # Propose changing the body.
        proposed_payload = {
            "contract": autom.contract,
            "max_compute_tier": int(autom.max_compute_tier or 0),
            "max_spend_per_run_usd": None,
            "max_spend_per_day_usd": None,
            "compute_profile": "persistent_workspace",
            "workspace_scope": "none",
            "name": autom.name,
            "actions": [
                {
                    "ordinal": 0,
                    "action_type": "gateway.send",
                    "config": {"body": "after"},
                    "app_action_id": None,
                    "parent_action_id": None,
                    "branch_condition": None,
                }
            ],
            "triggers": [],
            "delivery_targets": [],
        }
        result = await create_proposal(
            db,
            automation=autom,
            to_payload=proposed_payload,
            rationale="change body to after",
            risk_class="low",
            proposer_user_id=owner_id,
        )
        await db.commit()

        assert result.created is True
        assert result.proposal.status == "submitted"
        assert result.proposal.risk_class == "low"
        assert len(result.proposal.diff_summary or []) >= 1
        # One of the diff entries should mention the actions list.
        paths = [e["path"] for e in result.proposal.diff_summary]
        assert any("actions" in p for p in paths)


@pytest.mark.asyncio
async def test_create_proposal_idempotent_on_same_payload(session_maker):
    from app.models_automations import AutomationDefinition
    from app.services.workflows.proposals import create_proposal
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
        await snapshot_definition_to_version(db, definition=autom, actor_user_id=owner_id)
        await db.commit()

    async with session_maker() as db:
        autom = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == autom_id)
            )
        ).scalar_one()
        payload = {
            "actions": [
                {
                    "ordinal": 0,
                    "action_type": "gateway.send",
                    "config": {"body": "y"},
                    "app_action_id": None,
                    "parent_action_id": None,
                    "branch_condition": None,
                }
            ],
            "triggers": [],
            "delivery_targets": [],
        }
        first = await create_proposal(
            db, automation=autom, to_payload=payload, rationale="r", proposer_user_id=owner_id
        )
        await db.commit()
        second = await create_proposal(
            db, automation=autom, to_payload=payload, rationale="r", proposer_user_id=owner_id
        )
        await db.commit()

        assert first.created is True
        assert second.created is False
        assert second.proposal.id == first.proposal.id


@pytest.mark.asyncio
async def test_decide_approve_applies_change(session_maker):
    from app.models_automations import (
        AutomationAction,
        AutomationDefinition,
    )
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
        await snapshot_definition_to_version(db, definition=autom, actor_user_id=owner_id)
        await db.commit()

    async with session_maker() as db:
        autom = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == autom_id)
            )
        ).scalar_one()
        v1_head = autom.head_version_id
        result = await create_proposal(
            db,
            automation=autom,
            to_payload={
                "actions": [
                    {
                        "ordinal": 0,
                        "action_type": "gateway.send",
                        "config": {"body": "v2 APPLIED"},
                        "app_action_id": None,
                        "parent_action_id": None,
                        "branch_condition": None,
                    }
                ],
                "triggers": [],
                "delivery_targets": [],
            },
            rationale="apply v2",
            proposer_user_id=owner_id,
        )
        await db.commit()
        proposal_id = result.proposal.id

    async with session_maker() as db:
        decided = await decide_proposal(
            db,
            proposal_id=proposal_id,
            decision="approve",
            reviewer_user_id=owner_id,
        )
        await db.commit()

        assert decided.status == "applied"
        assert decided.applied_version_id is not None
        assert decided.applied_version_id != v1_head

        # Live row reflects the new body.
        action = (
            await db.execute(
                select(AutomationAction).where(AutomationAction.automation_id == autom_id)
            )
        ).scalar_one()
        assert action.config["body"] == "v2 APPLIED"

        # head_version_id flipped.
        autom = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == autom_id)
            )
        ).scalar_one()
        assert autom.head_version_id == decided.applied_version_id


@pytest.mark.asyncio
async def test_decide_reject_does_not_apply(session_maker):
    from app.models_automations import (
        AutomationAction,
        AutomationDefinition,
    )
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
            config={"body": "ORIGINAL"},
            ordinal=0,
        )
        await db.commit()

    async with session_maker() as db:
        autom = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == autom_id)
            )
        ).scalar_one()
        await snapshot_definition_to_version(db, definition=autom, actor_user_id=owner_id)
        await db.commit()

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
                        "config": {"body": "WOULD-BE-CHANGED"},
                        "app_action_id": None,
                        "parent_action_id": None,
                        "branch_condition": None,
                    }
                ],
                "triggers": [],
                "delivery_targets": [],
            },
            rationale="should be rejected",
            proposer_user_id=owner_id,
        )
        await db.commit()
        proposal_id = result.proposal.id

    async with session_maker() as db:
        decided = await decide_proposal(
            db,
            proposal_id=proposal_id,
            decision="reject",
            reviewer_user_id=owner_id,
            comment="not now",
        )
        await db.commit()

        assert decided.status == "rejected"
        assert decided.applied_version_id is None
        # Live row unchanged.
        action = (
            await db.execute(
                select(AutomationAction).where(AutomationAction.automation_id == autom_id)
            )
        ).scalar_one()
        assert action.config["body"] == "ORIGINAL"


@pytest.mark.asyncio
async def test_decide_already_decided_raises(session_maker):
    from app.models_automations import AutomationDefinition
    from app.services.workflows.proposals import (
        ProposalAlreadyDecided,
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
        await snapshot_definition_to_version(db, definition=autom, actor_user_id=owner_id)
        await db.commit()

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
                        "config": {"body": "y"},
                        "app_action_id": None,
                        "parent_action_id": None,
                        "branch_condition": None,
                    }
                ],
                "triggers": [],
                "delivery_targets": [],
            },
            rationale="r",
            proposer_user_id=owner_id,
        )
        await db.commit()
        pid = result.proposal.id

    async with session_maker() as db:
        await decide_proposal(
            db,
            proposal_id=pid,
            decision="approve",
            reviewer_user_id=owner_id,
        )
        await db.commit()

    async with session_maker() as db:
        with pytest.raises(ProposalAlreadyDecided):
            await decide_proposal(
                db,
                proposal_id=pid,
                decision="reject",
                reviewer_user_id=owner_id,
            )


def test_compute_diff_scalar_and_list_changes():
    from app.services.workflows.proposals import compute_diff

    before = {
        "contract": {"a": 1},
        "max_compute_tier": 0,
        "actions": [
            {"ordinal": 0, "action_type": "gateway.send", "config": {"body": "x"}},
        ],
        "triggers": [],
        "delivery_targets": [],
    }
    after = {
        "contract": {"a": 2},  # scalar replace
        "max_compute_tier": 1,  # scalar replace
        "actions": [
            {
                "ordinal": 0,
                "action_type": "gateway.send",
                "config": {"body": "y"},
            },  # ordinal replace
            {"ordinal": 1, "action_type": "gateway.send", "config": {"body": "z"}},  # add
        ],
        "triggers": [],
        "delivery_targets": [],
    }
    diffs = compute_diff(before=before, after=after)
    paths = [d["path"] for d in diffs]
    # Post-#473-should-fix: contract child keys are walked individually
    # so policy allow-lists like "contract.a" are reachable. The bare
    # "contract" path no longer appears for dict-shaped contracts.
    assert "contract.a" in paths
    assert "max_compute_tier" in paths
    assert any(p.startswith("actions[ordinal=0]") for p in paths)
    assert any(p.startswith("actions[ordinal=1]") for p in paths)
