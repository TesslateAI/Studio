"""Coverage for the post-blocker fixes (#473 / #474 should-fix items).

* compute_diff deep-walks contract child keys so
  ``allowed_changes: ["contract.allowed_tools"]`` policies are
  reachable.
* apply_proposal refuses callers that pass neither actor_user_id
  nor proposer_user_id (defense in depth).
* slack idempotency key prefers Slack's event_id / ts over
  body-hash so a user legitimately re-typing the same message
  doesn't dedupe into one run.
"""

from __future__ import annotations

import pytest


def test_compute_diff_walks_contract_child_keys():
    from app.services.workflows.proposals import compute_diff

    before = {"contract": {"allowed_tools": ["read_file"], "max_compute_tier": 0}}
    after = {"contract": {"allowed_tools": ["read_file", "bash"], "max_compute_tier": 0}}
    diff = compute_diff(before=before, after=after)
    paths = [e["path"] for e in diff]
    assert "contract.allowed_tools" in paths
    # Unchanged child key MUST NOT appear.
    assert "contract.max_compute_tier" not in paths


def test_compute_diff_contract_add_remove():
    from app.services.workflows.proposals import compute_diff

    before = {"contract": {"allowed_tools": ["read_file"]}}
    after = {"contract": {"allowed_mcps": ["filesystem"]}}
    diff = compute_diff(before=before, after=after)
    by_path = {e["path"]: e for e in diff}
    assert by_path["contract.allowed_tools"]["op"] == "remove"
    assert by_path["contract.allowed_mcps"]["op"] == "add"


def test_compute_diff_non_dict_contract_falls_back_to_replace():
    from app.services.workflows.proposals import compute_diff

    before = {"contract": "stringy"}
    after = {"contract": {"x": 1}}
    diff = compute_diff(before=before, after=after)
    paths = [e["path"] for e in diff]
    assert "contract" in paths


@pytest.mark.asyncio
async def test_apply_proposal_refuses_when_no_actor_or_proposer(session_maker):
    """Defense in depth: callers must supply at least one identity so an
    upstream skipped auth check can't silently let an unsigned mutation
    through.
    """
    import uuid
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.models_automations import AutomationDefinition
    from app.models_workflows import WorkflowProposal
    from app.services.workflows.proposals import ProposalError, apply_proposal

    from .conftest import seed_automation, seed_user

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        await db.commit()

    async with session_maker() as db:
        autom = (
            await db.execute(
                select(AutomationDefinition).where(AutomationDefinition.id == autom_id)
            )
        ).scalar_one()
        prop = WorkflowProposal(
            id=uuid.uuid4(),
            automation_id=autom.id,
            from_version_id=None,
            to_payload={},
            diff_summary=[],
            rationale="test",
            risk_class="low",
            status="submitted",
            proposer_user_id=None,
            proposer_run_id=None,
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
        )
        db.add(prop)
        await db.commit()

        with pytest.raises(ProposalError, match="actor"):
            await apply_proposal(db, proposal=prop, actor_user_id=None)


def test_slack_idempotency_prefers_event_id():
    import uuid

    from app.services.triggers.slack_message import _idempotency_key

    aid = uuid.uuid4()
    a = _idempotency_key(
        automation_id=aid,
        channel_id="C123",
        body="hello",
        user_id="U1",
        event_id="Ev0001",
    )
    b = _idempotency_key(
        automation_id=aid,
        channel_id="C123",
        body="completely different body",
        user_id="U99",
        event_id="Ev0001",
    )
    # Same event_id → same key even if body differs (legitimate retry).
    assert a == b


def test_slack_idempotency_falls_back_to_body_when_no_event_id():
    import uuid

    from app.services.triggers.slack_message import _idempotency_key

    aid = uuid.uuid4()
    a = _idempotency_key(
        automation_id=aid,
        channel_id="C123",
        body="hello",
        user_id="U1",
    )
    b = _idempotency_key(
        automation_id=aid,
        channel_id="C123",
        body="hello again",
        user_id="U1",
    )
    assert a != b


def test_slack_idempotency_same_body_legitimate_retype():
    """The bug we just fixed: with event_id supplied, re-typing the same
    message twice yields DIFFERENT keys so both runs fire. Without
    event_id we still dedupe (best-effort fallback), but real Slack
    callers always pass event_id."""
    import uuid

    from app.services.triggers.slack_message import _idempotency_key

    aid = uuid.uuid4()
    a = _idempotency_key(
        automation_id=aid,
        channel_id="C123",
        body="hello",
        user_id="U1",
        event_id="Ev0001",
    )
    b = _idempotency_key(
        automation_id=aid,
        channel_id="C123",
        body="hello",
        user_id="U1",
        event_id="Ev0002",  # different real Slack event → different run
    )
    assert a != b
