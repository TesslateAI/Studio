"""Budget interceptor: unlimited fallback, block on exhaustion, safe degrade."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models import AgentBudget
from app.services.agent_budget import check_budget, record_spend, reset_if_due


@pytest.mark.asyncio
async def test_no_row_means_unlimited(async_session) -> None:
    status = await check_budget(
        async_session,
        agent_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        pending_usd=1_000_000,
    )
    assert status.ok is True
    assert status.reason is None


@pytest.mark.asyncio
async def test_budget_blocks_when_exhausted(async_session) -> None:
    agent_id = uuid.uuid4()
    project_id = uuid.uuid4()
    row = AgentBudget(
        id=uuid.uuid4(),
        agent_id=agent_id,
        project_id=project_id,
        monthly_limit_usd=Decimal("10"),
        spent_usd=Decimal("10"),
        reset_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    async_session.add(row)
    await async_session.commit()

    status = await check_budget(
        async_session, agent_id=agent_id, project_id=project_id, pending_usd=Decimal("0.01")
    )
    assert status.ok is False
    assert status.reason


@pytest.mark.asyncio
async def test_agent_wide_fallback_when_project_row_missing(async_session) -> None:
    agent_id = uuid.uuid4()
    agent_wide = AgentBudget(
        id=uuid.uuid4(),
        agent_id=agent_id,
        project_id=None,
        monthly_limit_usd=Decimal("50"),
        spent_usd=Decimal("40"),
        reset_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    async_session.add(agent_wide)
    await async_session.commit()

    # No project-specific row — falls back to agent-wide, which has $10 remaining.
    ok = await check_budget(
        async_session, agent_id=agent_id, project_id=uuid.uuid4(), pending_usd=Decimal("5")
    )
    assert ok.ok is True

    blocked = await check_budget(
        async_session, agent_id=agent_id, project_id=uuid.uuid4(), pending_usd=Decimal("20")
    )
    assert blocked.ok is False


@pytest.mark.asyncio
async def test_record_spend_updates_existing_row(async_session) -> None:
    agent_id = uuid.uuid4()
    row = AgentBudget(
        id=uuid.uuid4(),
        agent_id=agent_id,
        project_id=None,
        monthly_limit_usd=Decimal("100"),
        spent_usd=Decimal("5"),
        reset_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    async_session.add(row)
    await async_session.commit()

    await record_spend(async_session, agent_id=agent_id, amount_usd=Decimal("7.25"))

    from sqlalchemy import select

    spent = (
        await async_session.execute(
            select(AgentBudget.spent_usd).where(AgentBudget.id == row.id)
        )
    ).scalar_one()
    assert Decimal(spent) == Decimal("12.25")


@pytest.mark.asyncio
async def test_reset_if_due_zeros_spend_and_advances_window(async_session) -> None:
    agent_id = uuid.uuid4()
    past = datetime.now(timezone.utc) - timedelta(days=1)
    row = AgentBudget(
        id=uuid.uuid4(),
        agent_id=agent_id,
        project_id=None,
        monthly_limit_usd=Decimal("10"),
        spent_usd=Decimal("10"),
        reset_at=past,
    )
    async_session.add(row)
    await async_session.commit()

    n = await reset_if_due(async_session)
    assert n == 1

    from sqlalchemy import select

    row_after = (
        await async_session.execute(
            select(AgentBudget.spent_usd, AgentBudget.reset_at).where(AgentBudget.id == row.id)
        )
    ).one()
    assert Decimal(row_after[0]) == Decimal("0")
    # SQLite returns naive datetimes; normalize to UTC for comparison.
    reset_at = row_after[1]
    if reset_at.tzinfo is None:
        reset_at = reset_at.replace(tzinfo=timezone.utc)
    assert reset_at > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_malformed_input_does_not_raise(async_session) -> None:
    # Passing an invalid UUID-compatible arg would normally blow up in the
    # dialect layer; check_budget swallows and returns unlimited.
    class Bogus:
        pass

    status = await check_budget(
        async_session,
        agent_id=Bogus(),  # type: ignore[arg-type]
        project_id=None,
        pending_usd=Decimal("1"),
    )
    assert status.ok is True
