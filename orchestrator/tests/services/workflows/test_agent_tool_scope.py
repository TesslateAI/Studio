"""Negative tests for G5 doctor scope enforcement (#469).

The doctor agent's contract carries ``allowed_workflow_ids``. Two
agent tools — ``manage_workflow_proposal`` and ``read_workflow_history``
— must refuse any automation_id not in that list, even if the
caller owns it. Without this, a doctor for workflow X could edit
or read any of the owner's other workflows.
"""

from __future__ import annotations

import pytest

from .conftest import seed_automation, seed_user


@pytest.mark.asyncio
async def test_manage_proposal_refuses_outside_allowed_workflow_ids(session_maker):
    from app.agent.tools.workflow_ops.manage_workflow_proposal import (
        manage_workflow_proposal_executor,
    )

    async with session_maker() as db:
        owner_id = await seed_user(db)
        target_id = await seed_automation(db, owner_user_id=owner_id)
        other_id = await seed_automation(db, owner_user_id=owner_id)
        await db.commit()

    async with session_maker() as db:
        context = {
            "db": db,
            "user_id": str(owner_id),
            "automation_run_id": None,
            # Doctor-style contract: only allowed to touch target_id.
            "contract": {"allowed_workflow_ids": [str(target_id)]},
        }
        # Listing proposals on the *other* automation must refuse even
        # though the caller owns it.
        result = await manage_workflow_proposal_executor(
            {"action": "list", "automation_id": str(other_id)},
            context,
        )
        assert result.get("success") is False
        assert "not owned" in (result.get("message") or "")


@pytest.mark.asyncio
async def test_manage_proposal_allows_within_allowed_workflow_ids(session_maker):
    from app.agent.tools.workflow_ops.manage_workflow_proposal import (
        manage_workflow_proposal_executor,
    )

    async with session_maker() as db:
        owner_id = await seed_user(db)
        target_id = await seed_automation(db, owner_user_id=owner_id)
        await db.commit()

    async with session_maker() as db:
        context = {
            "db": db,
            "user_id": str(owner_id),
            "automation_run_id": None,
            "contract": {"allowed_workflow_ids": [str(target_id)]},
        }
        result = await manage_workflow_proposal_executor(
            {"action": "list", "automation_id": str(target_id)},
            context,
        )
        assert result.get("success") is True


@pytest.mark.asyncio
async def test_manage_proposal_no_contract_still_owner_only(session_maker):
    """Backwards compat: a non-doctor agent context (no contract) keeps
    the original owner-only check — no regression."""
    from app.agent.tools.workflow_ops.manage_workflow_proposal import (
        manage_workflow_proposal_executor,
    )

    async with session_maker() as db:
        owner_id = await seed_user(db)
        other_owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=other_owner_id)
        await db.commit()

    async with session_maker() as db:
        context = {
            "db": db,
            "user_id": str(owner_id),
            "automation_run_id": None,
            "contract": None,
        }
        result = await manage_workflow_proposal_executor(
            {"action": "list", "automation_id": str(autom_id)},
            context,
        )
        assert result.get("success") is False


@pytest.mark.asyncio
async def test_read_workflow_history_refuses_outside_allowed_workflow_ids(session_maker):
    from app.agent.tools.workflow_ops.read_workflow_history import (
        read_workflow_history_executor,
    )

    async with session_maker() as db:
        owner_id = await seed_user(db)
        target_id = await seed_automation(db, owner_user_id=owner_id)
        other_id = await seed_automation(db, owner_user_id=owner_id)
        await db.commit()

    async with session_maker() as db:
        context = {
            "db": db,
            "user_id": str(owner_id),
            "contract": {"allowed_workflow_ids": [str(target_id)]},
        }
        result = await read_workflow_history_executor(
            {"automation_id": str(other_id), "limit": 5},
            context,
        )
        assert result.get("success") is False
        assert "allowed scope" in (result.get("message") or "")


@pytest.mark.asyncio
async def test_read_workflow_history_allows_within_allowed_workflow_ids(session_maker):
    from app.agent.tools.workflow_ops.read_workflow_history import (
        read_workflow_history_executor,
    )

    async with session_maker() as db:
        owner_id = await seed_user(db)
        target_id = await seed_automation(db, owner_user_id=owner_id)
        await db.commit()

    async with session_maker() as db:
        context = {
            "db": db,
            "user_id": str(owner_id),
            "contract": {"allowed_workflow_ids": [str(target_id)]},
        }
        result = await read_workflow_history_executor(
            {"automation_id": str(target_id), "limit": 5},
            context,
        )
        assert result.get("success") is True
