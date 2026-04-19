"""Integration tests for services/litellm_keys against a real Postgres.

Requires the test container from tests/integration/conftest.py (port 5433).
The LiteLLM proxy itself is not called — we inject a FakeDelegate that
records the mint/revoke calls. The DB is real (needed for SELECT FOR UPDATE,
self-FK, and the partial TTL index).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import litellm_keys
from app.services.apps.key_lifecycle import (
    KeyMintError,
    KeyState,
    KeyTier,
)

pytestmark = pytest.mark.integration


class FakeDelegate:
    """Records calls so tests can assert without hitting LiteLLM."""

    def __init__(self) -> None:
        self.minted: list[dict[str, Any]] = []
        self.revoked: list[str] = []
        self._counter = 0
        self.fail_on_mint = False
        self.fail_on_revoke = False

    async def create_scoped_key(
        self,
        *,
        tier: str,
        budget_usd: Decimal,
        ttl_seconds: int,
        metadata: dict[str, Any],
    ) -> dict[str, str]:
        if self.fail_on_mint:
            raise RuntimeError("simulated litellm mint failure")
        self._counter += 1
        key_id = f"test-key-{self._counter}-{uuid.uuid4().hex[:8]}"
        self.minted.append(
            {
                "key_id": key_id,
                "tier": tier,
                "budget_usd": Decimal(budget_usd),
                "metadata": metadata,
            }
        )
        return {"key_id": key_id, "api_key": f"sk-fake-{key_id}"}

    async def revoke_key(self, key_id: str) -> None:
        if self.fail_on_revoke:
            raise RuntimeError("simulated litellm revoke failure")
        self.revoked.append(key_id)


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    import os

    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test"
    )
    engine = create_async_engine(url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, class_=_AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
def delegate() -> FakeDelegate:
    return FakeDelegate()


# -- mint --------------------------------------------------------------------


async def test_mint_session_key_writes_active_ledger_row(db, delegate) -> None:
    row = await litellm_keys.mint(
        db,
        delegate=delegate,
        tier=KeyTier.SESSION,
        user_id=None,
        budget_usd=Decimal("1.00"),
        session_id=uuid.uuid4(),
    )
    assert row.state == KeyState.ACTIVE.value
    assert row.tier == KeyTier.SESSION.value
    assert row.budget_usd == Decimal("1.000000")
    assert row.spent_usd == Decimal("0")
    assert row.ttl_at is not None and row.ttl_at > datetime.now(tz=UTC)
    assert len(delegate.minted) == 1
    assert delegate.minted[0]["tier"] == "session"


async def test_mint_invocation_key_ok(db, delegate) -> None:
    row = await litellm_keys.mint(
        db,
        delegate=delegate,
        tier=KeyTier.INVOCATION,
        user_id=None,
        budget_usd=Decimal("0.25"),
    )
    assert row.tier == KeyTier.INVOCATION.value
    assert row.state == KeyState.ACTIVE.value


async def test_mint_nested_requires_parent(db, delegate) -> None:
    with pytest.raises(KeyMintError):
        await litellm_keys.mint(
            db,
            delegate=delegate,
            tier=KeyTier.NESTED,
            user_id=None,
            budget_usd=Decimal("0.10"),
        )


async def test_mint_nested_under_active_parent(db, delegate) -> None:
    parent = await litellm_keys.mint(
        db, delegate=delegate, tier=KeyTier.SESSION, user_id=None, budget_usd=Decimal("1.00")
    )
    child = await litellm_keys.mint(
        db,
        delegate=delegate,
        tier=KeyTier.NESTED,
        user_id=None,
        budget_usd=Decimal("0.20"),
        parent_key_id=parent.key_id,
    )
    assert child.parent_key_id == parent.key_id
    assert child.state == KeyState.ACTIVE.value


async def test_mint_nested_rejects_when_over_parent_remaining(db, delegate) -> None:
    parent = await litellm_keys.mint(
        db, delegate=delegate, tier=KeyTier.SESSION, user_id=None, budget_usd=Decimal("0.50")
    )
    # burn 0.40 on parent
    await litellm_keys.record_spend(db, key_id=parent.key_id, delta_usd=Decimal("0.40"))
    with pytest.raises(KeyMintError, match="exceeds parent remaining"):
        await litellm_keys.mint(
            db,
            delegate=delegate,
            tier=KeyTier.NESTED,
            user_id=None,
            budget_usd=Decimal("0.25"),
            parent_key_id=parent.key_id,
        )


async def test_mint_depth_limit_enforced(db, delegate, monkeypatch) -> None:
    monkeypatch.setattr(litellm_keys, "NESTED_MAX_DEPTH", 2)
    p1 = await litellm_keys.mint(
        db, delegate=delegate, tier=KeyTier.SESSION, user_id=None, budget_usd=Decimal("10")
    )
    p2 = await litellm_keys.mint(
        db,
        delegate=delegate,
        tier=KeyTier.NESTED,
        user_id=None,
        budget_usd=Decimal("1"),
        parent_key_id=p1.key_id,
    )
    p3 = await litellm_keys.mint(
        db,
        delegate=delegate,
        tier=KeyTier.NESTED,
        user_id=None,
        budget_usd=Decimal("0.5"),
        parent_key_id=p2.key_id,
    )
    with pytest.raises(KeyMintError, match="depth"):
        await litellm_keys.mint(
            db,
            delegate=delegate,
            tier=KeyTier.NESTED,
            user_id=None,
            budget_usd=Decimal("0.1"),
            parent_key_id=p3.key_id,
        )


async def test_mint_failure_at_litellm_leaves_no_row(db, delegate) -> None:
    delegate.fail_on_mint = True
    with pytest.raises(RuntimeError):
        await litellm_keys.mint(
            db,
            delegate=delegate,
            tier=KeyTier.SESSION,
            user_id=None,
            budget_usd=Decimal("1.0"),
        )
    assert delegate.minted == []


# -- record_spend ------------------------------------------------------------


async def test_record_spend_accrues_on_leaf(db, delegate) -> None:
    row = await litellm_keys.mint(
        db, delegate=delegate, tier=KeyTier.SESSION, user_id=None, budget_usd=Decimal("1.0")
    )
    updated = await litellm_keys.record_spend(db, key_id=row.key_id, delta_usd=Decimal("0.25"))
    assert updated.spent_usd == Decimal("0.250000")


async def test_record_spend_cascades_to_ancestors(db, delegate) -> None:
    p1 = await litellm_keys.mint(
        db, delegate=delegate, tier=KeyTier.SESSION, user_id=None, budget_usd=Decimal("10")
    )
    p2 = await litellm_keys.mint(
        db,
        delegate=delegate,
        tier=KeyTier.NESTED,
        user_id=None,
        budget_usd=Decimal("5"),
        parent_key_id=p1.key_id,
    )
    p3 = await litellm_keys.mint(
        db,
        delegate=delegate,
        tier=KeyTier.NESTED,
        user_id=None,
        budget_usd=Decimal("1"),
        parent_key_id=p2.key_id,
    )
    await litellm_keys.record_spend(db, key_id=p3.key_id, delta_usd=Decimal("0.5"))

    await db.refresh(p1)
    await db.refresh(p2)
    await db.refresh(p3)
    assert p3.spent_usd == Decimal("0.500000")
    assert p2.spent_usd == Decimal("0.500000")
    assert p1.spent_usd == Decimal("0.500000")


async def test_record_spend_rejects_negative_delta(db, delegate) -> None:
    row = await litellm_keys.mint(
        db, delegate=delegate, tier=KeyTier.SESSION, user_id=None, budget_usd=Decimal("1.0")
    )
    with pytest.raises(ValueError):
        await litellm_keys.record_spend(db, key_id=row.key_id, delta_usd=Decimal("-0.01"))


# -- settlement --------------------------------------------------------------


async def test_begin_and_finalize_settlement(db, delegate) -> None:
    row = await litellm_keys.mint(
        db, delegate=delegate, tier=KeyTier.INVOCATION, user_id=None, budget_usd=Decimal("1.0")
    )
    settling = await litellm_keys.begin_settlement(
        db, delegate=delegate, key_id=row.key_id, reason="complete"
    )
    assert settling.state == KeyState.SETTLING.value
    assert row.key_id in delegate.revoked

    settled = await litellm_keys.finalize_settlement(db, key_id=row.key_id)
    assert settled.state == KeyState.SETTLED.value


async def test_finalize_settlement_idempotent(db, delegate) -> None:
    row = await litellm_keys.mint(
        db, delegate=delegate, tier=KeyTier.INVOCATION, user_id=None, budget_usd=Decimal("1.0")
    )
    await litellm_keys.begin_settlement(db, delegate=delegate, key_id=row.key_id)
    await litellm_keys.finalize_settlement(db, key_id=row.key_id)
    # second call is a no-op, not an error
    again = await litellm_keys.finalize_settlement(db, key_id=row.key_id)
    assert again.state == KeyState.SETTLED.value


async def test_begin_settlement_on_terminal_row_is_noop(db, delegate) -> None:
    row = await litellm_keys.mint(
        db, delegate=delegate, tier=KeyTier.INVOCATION, user_id=None, budget_usd=Decimal("1.0")
    )
    await litellm_keys.begin_settlement(db, delegate=delegate, key_id=row.key_id)
    await litellm_keys.finalize_settlement(db, key_id=row.key_id)
    # Begin again — terminal, no revoke call added, row stays settled
    before_revokes = len(delegate.revoked)
    after = await litellm_keys.begin_settlement(db, delegate=delegate, key_id=row.key_id)
    assert after.state == KeyState.SETTLED.value
    assert len(delegate.revoked) == before_revokes


# -- cascade revoke ----------------------------------------------------------


async def test_cascade_revoke_hits_all_descendants(db, delegate) -> None:
    parent = await litellm_keys.mint(
        db, delegate=delegate, tier=KeyTier.SESSION, user_id=None, budget_usd=Decimal("10")
    )
    child_a = await litellm_keys.mint(
        db,
        delegate=delegate,
        tier=KeyTier.NESTED,
        user_id=None,
        budget_usd=Decimal("1"),
        parent_key_id=parent.key_id,
    )
    child_b = await litellm_keys.mint(
        db,
        delegate=delegate,
        tier=KeyTier.NESTED,
        user_id=None,
        budget_usd=Decimal("1"),
        parent_key_id=parent.key_id,
    )
    grandchild = await litellm_keys.mint(
        db,
        delegate=delegate,
        tier=KeyTier.NESTED,
        user_id=None,
        budget_usd=Decimal("0.5"),
        parent_key_id=child_a.key_id,
    )

    revoked = await litellm_keys.cascade_revoke(db, delegate=delegate, parent_key_id=parent.key_id)
    assert set(revoked) == {child_a.key_id, child_b.key_id, grandchild.key_id}
    await db.refresh(parent)
    assert parent.state == KeyState.ACTIVE.value, "cascade does not revoke the parent itself"


async def test_cascade_revoke_skips_already_terminal(db, delegate) -> None:
    parent = await litellm_keys.mint(
        db, delegate=delegate, tier=KeyTier.SESSION, user_id=None, budget_usd=Decimal("5")
    )
    child = await litellm_keys.mint(
        db,
        delegate=delegate,
        tier=KeyTier.NESTED,
        user_id=None,
        budget_usd=Decimal("1"),
        parent_key_id=parent.key_id,
    )
    # pre-settle the child
    await litellm_keys.begin_settlement(db, delegate=delegate, key_id=child.key_id)
    await litellm_keys.finalize_settlement(db, key_id=child.key_id)

    before = len(delegate.revoked)
    revoked = await litellm_keys.cascade_revoke(db, delegate=delegate, parent_key_id=parent.key_id)
    assert child.key_id not in revoked
    assert len(delegate.revoked) == before  # no new revokes issued


# -- await_children_terminal -------------------------------------------------


async def test_await_children_terminal_true_when_no_children(db, delegate) -> None:
    row = await litellm_keys.mint(
        db, delegate=delegate, tier=KeyTier.SESSION, user_id=None, budget_usd=Decimal("1")
    )
    assert await litellm_keys.await_children_terminal(db, parent_key_id=row.key_id)


async def test_await_children_terminal_false_with_active_child(db, delegate) -> None:
    parent = await litellm_keys.mint(
        db, delegate=delegate, tier=KeyTier.SESSION, user_id=None, budget_usd=Decimal("1")
    )
    await litellm_keys.mint(
        db,
        delegate=delegate,
        tier=KeyTier.NESTED,
        user_id=None,
        budget_usd=Decimal("0.1"),
        parent_key_id=parent.key_id,
    )
    assert not await litellm_keys.await_children_terminal(db, parent_key_id=parent.key_id)


# -- reaper ------------------------------------------------------------------


async def test_select_idle_session_keys_returns_keys_past_ttl(db, delegate) -> None:
    row = await litellm_keys.mint(
        db,
        delegate=delegate,
        tier=KeyTier.SESSION,
        user_id=None,
        budget_usd=Decimal("1"),
        ttl_seconds=60,
    )
    # Force TTL into the past.
    row.ttl_at = datetime.now(tz=UTC) - timedelta(seconds=5)
    await db.flush()

    idle = await litellm_keys.select_idle_session_keys(db)
    assert row.key_id in idle


async def test_select_idle_session_keys_skips_invocation_tier(db, delegate) -> None:
    row = await litellm_keys.mint(
        db,
        delegate=delegate,
        tier=KeyTier.INVOCATION,
        user_id=None,
        budget_usd=Decimal("1"),
        ttl_seconds=60,
    )
    row.ttl_at = datetime.now(tz=UTC) - timedelta(seconds=5)
    await db.flush()

    idle = await litellm_keys.select_idle_session_keys(db)
    assert row.key_id not in idle


async def test_bump_session_ttl_defers_reaping(db, delegate) -> None:
    row = await litellm_keys.mint(
        db,
        delegate=delegate,
        tier=KeyTier.SESSION,
        user_id=None,
        budget_usd=Decimal("1"),
        ttl_seconds=60,
    )
    row.ttl_at = datetime.now(tz=UTC) - timedelta(seconds=5)
    await db.flush()

    bumped = await litellm_keys.bump_session_ttl(db, key_id=row.key_id)
    assert bumped.ttl_at > datetime.now(tz=UTC)
    idle = await litellm_keys.select_idle_session_keys(db)
    assert row.key_id not in idle
