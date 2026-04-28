"""Phase 2 — unit tests for ``services.automations.budget``.

Mirrors the SQLite-alembic-head fixture pattern from
``test_dispatcher.py`` so we exercise the real ``automation_definitions``
schema (including the ``parent_automation_id`` FK + check constraints).

Redis is stubbed with an in-process ``_FakeRedis`` that implements the
small surface ``budget`` actually uses (``set/get/eval/incrby/exists/
delete/publish/pubsub``). The Lua reservation script is reimplemented in
Python in the fake so we can assert on floor-breach behavior without
spinning up a real Redis.

LiteLLM is stubbed with a ``_FakeDelegate`` that records mint/revoke
calls and returns deterministic key ids.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Migration fixture (same shape as test_dispatcher.py).
# ---------------------------------------------------------------------------


def _install_sqlite_now(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ARG001
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.now(UTC).isoformat(sep=" ")
        )


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[3]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def migrated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    db_path = tmp_path / "budget.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")

    from app.config import get_settings

    get_settings.cache_clear()
    orchestrator_dir = Path(__file__).resolve().parents[3]
    original = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original)
    yield url
    get_settings.cache_clear()


@pytest.fixture
def session_maker(migrated_sqlite: str):
    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    asyncio.run(engine.dispose())


# ---------------------------------------------------------------------------
# In-process Redis fake (only the surface ``budget.py`` exercises).
# ---------------------------------------------------------------------------


class _FakePubSub:
    def __init__(self, owner: "_FakeRedis") -> None:
        self._owner = owner
        self._channel: str | None = None
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def subscribe(self, channel: str) -> None:
        self._channel = channel
        self._owner._subscribers[channel].append(self)
        # The real client emits a subscribe-confirm first; mimic so the
        # caller's filter for type=='message' is exercised.
        await self._queue.put({"type": "subscribe", "channel": channel, "data": 1})

    async def unsubscribe(self, channel: str) -> None:
        subs = self._owner._subscribers.get(channel, [])
        if self in subs:
            subs.remove(self)

    async def close(self) -> None:
        pass

    async def listen(self):
        while True:
            msg = await self._queue.get()
            yield msg

    async def deliver(self, payload: str) -> None:
        await self._queue.put(
            {"type": "message", "channel": self._channel, "data": payload}
        )


class _FakeRedis:
    """Minimal in-memory stand-in for ``redis.asyncio.Redis``.

    Supports the operations ``budget.py`` actually uses. The Lua script
    is dispatched to a Python implementation that mirrors the contract.
    """

    def __init__(self) -> None:
        self._kv: dict[str, int] = {}
        self._ttl: dict[str, int] = {}
        self._subscribers: dict[str, list[_FakePubSub]] = defaultdict(list)
        self.published: list[tuple[str, str]] = []

    async def set(
        self,
        key: str,
        value: Any,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool | None:
        if nx and key in self._kv:
            return None
        self._kv[key] = int(value)
        if ex is not None:
            self._ttl[key] = ex
        return True

    async def get(self, key: str) -> str | None:
        if key not in self._kv:
            return None
        return str(self._kv[key])

    async def exists(self, key: str) -> int:
        return 1 if key in self._kv else 0

    async def incrby(self, key: str, amount: int) -> int:
        self._kv[key] = self._kv.get(key, 0) + int(amount)
        return self._kv[key]

    async def delete(self, key: str) -> int:
        return 1 if self._kv.pop(key, None) is not None else 0

    async def eval(self, script: str, numkeys: int, *args: Any) -> int:
        # ``budget.py`` only ships one Lua script (the reserve-with-floor).
        # Reimplement its semantics in Python so tests can assert without
        # a real Redis.
        key = args[0]
        decrement = int(args[1])
        if key not in self._kv:
            return -2
        cur = self._kv[key]
        if cur - decrement < 0:
            return -1
        self._kv[key] = cur - decrement
        return self._kv[key]

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        for sub in list(self._subscribers.get(channel, [])):
            await sub.deliver(message)
        return len(self._subscribers.get(channel, []))

    def pubsub(self) -> _FakePubSub:
        return _FakePubSub(self)


# ---------------------------------------------------------------------------
# Fake LiteLLM delegate (records calls, returns deterministic ids).
# ---------------------------------------------------------------------------


class _FakeDelegate:
    def __init__(self) -> None:
        self.minted: list[dict[str, Any]] = []
        self.revoked: list[str] = []
        self._next_secret = 0

    async def create_scoped_key(
        self,
        *,
        tier: str,
        budget_usd: Decimal,
        ttl_seconds: int,
        metadata: dict[str, Any],
    ) -> dict[str, str]:
        self._next_secret += 1
        secret = f"sk-fake-{self._next_secret:08d}"
        key_id = uuid.uuid4().hex
        self.minted.append(
            {
                "tier": tier,
                "budget_usd": Decimal(budget_usd),
                "ttl_seconds": ttl_seconds,
                "metadata": metadata,
                "key_id": key_id,
                "api_key": secret,
            }
        )
        return {"key_id": key_id, "api_key": secret}

    async def revoke_key(self, key_id: str) -> None:
        self.revoked.append(key_id)


# ---------------------------------------------------------------------------
# Seed helpers.
# ---------------------------------------------------------------------------


async def _seed_user(db) -> uuid.UUID:
    from sqlalchemy import insert as core_insert

    from app.models_auth import User

    user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(User.__table__).values(
            id=user_id,
            email=f"test-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Test",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
        )
    )
    await db.flush()
    return user_id


async def _seed_automation(
    db,
    *,
    owner_user_id: uuid.UUID,
    parent_automation_id: uuid.UUID | None = None,
    max_per_day: Decimal | None = None,
    depth: int = 0,
) -> uuid.UUID:
    from app.models_automations import AutomationDefinition

    autom = AutomationDefinition(
        id=uuid.uuid4(),
        name="test-automation",
        owner_user_id=owner_user_id,
        workspace_scope="none",
        contract={
            "allowed_tools": ["read_file"],
            "max_compute_tier": 0,
            "on_breach": "pause_for_approval",
        },
        max_compute_tier=0,
        max_spend_per_day_usd=max_per_day,
        is_active=True,
        parent_automation_id=parent_automation_id,
        depth=depth,
    )
    db.add(autom)
    await db.flush()
    return autom.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_allocate_run_budget_happy_path(session_maker) -> None:
    """Mints a key, debits daily, returns BudgetAllocation."""
    from app.services.automations.budget import allocate_run_budget

    redis = _FakeRedis()
    delegate = _FakeDelegate()

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(
                db, owner_user_id=user_id, max_per_day=Decimal("1.00")
            )
            await db.commit()

        async with session_maker() as db:
            return await allocate_run_budget(
                db,
                run_id=uuid.uuid4(),
                automation_id=automation_id,
                contract={
                    "allowed_tools": ["read_file"],
                    "max_compute_tier": 0,
                    "max_spend_per_run_usd": "0.10",
                    "max_spend_per_day_usd": "1.00",
                },
                redis_client=redis,
                delegate=delegate,
            )

    allocation = asyncio.run(go())
    assert allocation.max_usd_per_run == Decimal("0.10")
    assert allocation.daily_remaining_usd == Decimal("0.90")
    assert allocation.is_extension is False
    assert allocation.litellm_key_id  # non-empty
    assert len(delegate.minted) == 1
    assert delegate.minted[0]["budget_usd"] == Decimal("0.10")

    # Critical: the allocation must carry the FULL ``sk-...`` secret so
    # the agent worker can inject it into LiteLLM ``Authorization``
    # headers. The 8-char preview that's persisted in
    # ``LiteLLMKeyLedger.meta.api_key_preview`` (security policy) is
    # NOT sufficient — auth would fail on the first request. See
    # :class:`services.litellm_keys.MintResult` for the contract.
    expected_secret = delegate.minted[0]["api_key"]
    assert allocation.litellm_key_value == expected_secret
    assert allocation.litellm_key_value.startswith("sk-")
    # Guard against regression to the 8-char preview.
    assert len(allocation.litellm_key_value) > 8
    assert allocation.litellm_key_value != expected_secret[:8]


@pytest.mark.unit
def test_allocate_raises_when_daily_exceeded(session_maker) -> None:
    """Per-run cap larger than remaining daily -> DailyBudgetExceeded."""
    from app.services.automations.budget import (
        DailyBudgetExceeded,
        allocate_run_budget,
    )

    redis = _FakeRedis()
    delegate = _FakeDelegate()

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(
                db, owner_user_id=user_id, max_per_day=Decimal("0.05")
            )
            await db.commit()

        async with session_maker() as db:
            return await allocate_run_budget(
                db,
                run_id=uuid.uuid4(),
                automation_id=automation_id,
                contract={
                    "allowed_tools": [],
                    "max_compute_tier": 0,
                    "max_spend_per_run_usd": "0.10",
                    "max_spend_per_day_usd": "0.05",
                },
                redis_client=redis,
                delegate=delegate,
            )

    with pytest.raises(DailyBudgetExceeded) as exc_info:
        asyncio.run(go())

    assert exc_info.value.requested_usd == Decimal("0.10")
    assert exc_info.value.remaining_usd == Decimal("0.05")
    # No key minted on the cheap path failure.
    assert delegate.minted == []


@pytest.mark.unit
def test_deallocate_refunds_unused_and_revokes_key(session_maker) -> None:
    """Refund (max - actual_spend) and delete the key."""
    from app.services.automations.budget import (
        allocate_run_budget,
        deallocate_run_budget,
    )

    redis = _FakeRedis()
    delegate = _FakeDelegate()

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(
                db, owner_user_id=user_id, max_per_day=Decimal("1.00")
            )
            await db.commit()

        run_id = uuid.uuid4()
        async with session_maker() as db:
            allocation = await allocate_run_budget(
                db,
                run_id=run_id,
                automation_id=automation_id,
                contract={
                    "max_spend_per_run_usd": "0.50",
                    "max_spend_per_day_usd": "1.00",
                    "allowed_tools": [],
                    "max_compute_tier": 0,
                },
                redis_client=redis,
                delegate=delegate,
            )

        # Daily was 1.00 -> 0.50 after debit.
        async with session_maker() as db:
            await deallocate_run_budget(
                db,
                run_id=run_id,
                automation_id=automation_id,
                allocation=allocation,
                actual_spend_usd=Decimal("0.10"),
                redis_client=redis,
                delegate=delegate,
            )
        return allocation

    allocation = asyncio.run(go())
    # Refund of 0.40 (0.50 cap - 0.10 actual). Daily now 0.90.
    from app.services.automations.budget import _MICRO_PER_USD, _R_DAILY_KEY  # type: ignore

    # Find the automation's daily key in the fake redis.
    daily_keys = [k for k in redis._kv if k.startswith("tesslate:budget:daily:")]
    assert len(daily_keys) == 1
    remaining = Decimal(redis._kv[daily_keys[0]]) / _MICRO_PER_USD
    assert remaining == Decimal("0.90")
    assert allocation.litellm_key_id in delegate.revoked


@pytest.mark.unit
def test_request_budget_extension_deduplicates_concurrent_callers(
    session_maker,
) -> None:
    """First caller acquires the lock; second caller awaits pubsub."""
    from app.services.automations.budget import (
        publish_extension_resolution,
        request_budget_extension,
    )

    redis = _FakeRedis()
    run_id = uuid.uuid4()

    async def go():
        # First caller: should acquire and return True.
        first = await request_budget_extension(
            run_id=run_id,
            extension_usd=Decimal("0.10"),
            redis_client=redis,
            timeout_seconds=2.0,
        )

        # Second caller: lock is held -> awaits pubsub. Schedule the
        # resolution publish after a short delay so the awaiter wakes.
        async def _publish_later():
            await asyncio.sleep(0.05)
            await publish_extension_resolution(
                run_id=run_id, approved=True, redis_client=redis
            )

        publish_task = asyncio.create_task(_publish_later())
        second = await request_budget_extension(
            run_id=run_id,
            extension_usd=Decimal("0.10"),
            redis_client=redis,
            timeout_seconds=2.0,
        )
        await publish_task
        return first, second

    first, second = asyncio.run(go())
    assert first is True
    assert second is True
    # Resolution was published once.
    assert any(p[1] == "approved" for p in redis.published)


@pytest.mark.unit
def test_cycle_detection_in_parent_chain(session_maker) -> None:
    """A -> B -> A walk raises CycleDetected.

    The DB has check constraints that ban most cycles, but the walker is
    defensive — we manually wire a 2-cycle via raw UPDATEs to bypass the
    application-level guards and assert the walker still catches it.
    """
    from sqlalchemy import update

    from app.models_automations import AutomationDefinition
    from app.services.automations.budget import CycleDetected, _walk_parent_chain

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            a_id = await _seed_automation(db, owner_user_id=user_id)
            b_id = await _seed_automation(
                db, owner_user_id=user_id, parent_automation_id=a_id, depth=1
            )
            # Force the cycle: A.parent = B. Use raw UPDATE to skip ORM
            # validation hooks.
            await db.execute(
                update(AutomationDefinition)
                .where(AutomationDefinition.id == a_id)
                .values(parent_automation_id=b_id)
            )
            await db.commit()

        async with session_maker() as db:
            await _walk_parent_chain(db, a_id)

    with pytest.raises(CycleDetected):
        asyncio.run(go())


@pytest.mark.unit
def test_parent_chain_debits_both_levels(session_maker) -> None:
    """Child run debits both child + parent daily counters."""
    from app.services.automations.budget import (
        _MICRO_PER_USD,
        _R_DAILY_KEY,
        allocate_run_budget,
    )

    redis = _FakeRedis()
    delegate = _FakeDelegate()

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            parent_id = await _seed_automation(
                db, owner_user_id=user_id, max_per_day=Decimal("2.00")
            )
            child_id = await _seed_automation(
                db,
                owner_user_id=user_id,
                parent_automation_id=parent_id,
                max_per_day=Decimal("1.00"),
                depth=1,
            )
            await db.commit()

        async with session_maker() as db:
            await allocate_run_budget(
                db,
                run_id=uuid.uuid4(),
                automation_id=child_id,
                contract={
                    "max_spend_per_run_usd": "0.30",
                    "max_spend_per_day_usd": "1.00",
                    "allowed_tools": [],
                    "max_compute_tier": 0,
                },
                redis_client=redis,
                delegate=delegate,
            )
        return parent_id, child_id

    parent_id, child_id = asyncio.run(go())
    parent_key = _R_DAILY_KEY.format(automation_id=str(parent_id))
    child_key = _R_DAILY_KEY.format(automation_id=str(child_id))

    parent_remaining = Decimal(redis._kv[parent_key]) / _MICRO_PER_USD
    child_remaining = Decimal(redis._kv[child_key]) / _MICRO_PER_USD

    # Parent: 2.00 - 0.30 = 1.70; child: 1.00 - 0.30 = 0.70.
    assert parent_remaining == Decimal("1.70")
    assert child_remaining == Decimal("0.70")


@pytest.mark.unit
def test_parent_overflow_refunds_child_debit(session_maker) -> None:
    """If parent's daily is exhausted, the child's debit is refunded
    before raising — no partial reservation leaks."""
    from app.services.automations.budget import (
        _MICRO_PER_USD,
        _R_DAILY_KEY,
        DailyBudgetExceeded,
        allocate_run_budget,
    )

    redis = _FakeRedis()
    delegate = _FakeDelegate()

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            # Parent has only $0.05 daily; child has $1.00. Child's
            # $0.10 per-run debit succeeds at the child level then fails
            # at the parent level — child-side debit must be refunded.
            parent_id = await _seed_automation(
                db, owner_user_id=user_id, max_per_day=Decimal("0.05")
            )
            child_id = await _seed_automation(
                db,
                owner_user_id=user_id,
                parent_automation_id=parent_id,
                max_per_day=Decimal("1.00"),
                depth=1,
            )
            await db.commit()

        async with session_maker() as db:
            try:
                await allocate_run_budget(
                    db,
                    run_id=uuid.uuid4(),
                    automation_id=child_id,
                    contract={
                        "max_spend_per_run_usd": "0.10",
                        "max_spend_per_day_usd": "1.00",
                        "allowed_tools": [],
                        "max_compute_tier": 0,
                    },
                    redis_client=redis,
                    delegate=delegate,
                )
            except DailyBudgetExceeded:
                pass  # expected
        return parent_id, child_id

    parent_id, child_id = asyncio.run(go())
    parent_key = _R_DAILY_KEY.format(automation_id=str(parent_id))
    child_key = _R_DAILY_KEY.format(automation_id=str(child_id))

    # Child must be back at full $1.00 (debit refunded).
    assert Decimal(redis._kv[child_key]) / _MICRO_PER_USD == Decimal("1.00")
    # Parent stays at $0.05 (decrement was rejected by Lua floor check).
    assert Decimal(redis._kv[parent_key]) / _MICRO_PER_USD == Decimal("0.05")
    # No key minted on cheap-path failure.
    assert delegate.minted == []


@pytest.mark.unit
def test_no_daily_cap_returns_infinite_remaining(session_maker) -> None:
    """When ``max_spend_per_day_usd`` is unset on the automation, the
    daily counter is never created and the allocator returns
    ``Decimal('Infinity')`` for remaining."""
    from app.services.automations.budget import allocate_run_budget

    redis = _FakeRedis()
    delegate = _FakeDelegate()

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(
                db, owner_user_id=user_id, max_per_day=None
            )
            await db.commit()

        async with session_maker() as db:
            return await allocate_run_budget(
                db,
                run_id=uuid.uuid4(),
                automation_id=automation_id,
                contract={
                    "max_spend_per_run_usd": "0.10",
                    "allowed_tools": [],
                    "max_compute_tier": 0,
                },
                redis_client=redis,
                delegate=delegate,
            )

    allocation = asyncio.run(go())
    assert allocation.daily_remaining_usd == Decimal("Infinity")
    # No daily key created.
    assert all(not k.startswith("tesslate:budget:daily:") for k in redis._kv)
    # But key was still minted.
    assert len(delegate.minted) == 1


@pytest.mark.unit
def test_invalid_contract_raises_value_error(session_maker) -> None:
    from app.services.automations.budget import allocate_run_budget

    redis = _FakeRedis()
    delegate = _FakeDelegate()

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(db, owner_user_id=user_id)
            await db.commit()

        async with session_maker() as db:
            return await allocate_run_budget(
                db,
                run_id=uuid.uuid4(),
                automation_id=automation_id,
                contract={"allowed_tools": [], "max_compute_tier": 0},
                redis_client=redis,
                delegate=delegate,
            )

    with pytest.raises(ValueError, match="max_spend_per_run_usd"):
        asyncio.run(go())
