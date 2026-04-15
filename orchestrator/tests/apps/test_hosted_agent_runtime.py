"""Wave 6 — unit tests for hosted-agent runtime + warm pool.

Integration tests (live DB) are out of scope for this module's unit brief;
mark any future live-DB cases with `@pytest.mark.integration`.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from app.services.apps import hosted_agent_runtime, warm_pool
from app.services.apps.hosted_agent_runtime import (
    AgentNotDeclaredError,
    begin_hosted_invocation,
    list_declared_agents,
)
from app.services.apps.key_lifecycle import KeyState, KeyTier


# ---------------------------------------------------------------------------
# FakeDelegate (Wave 0 pattern)
# ---------------------------------------------------------------------------


class FakeDelegate:
    def __init__(self) -> None:
        self.minted: list[dict[str, Any]] = []
        self.revoked: list[str] = []
        self._counter = 0

    async def create_scoped_key(
        self,
        *,
        tier: str,
        budget_usd: Decimal,
        ttl_seconds: int,
        metadata: dict[str, Any],
    ) -> dict[str, str]:
        self._counter += 1
        key_id = f"ha-key-{self._counter}-{uuid.uuid4().hex[:6]}"
        api_key = f"sk-fake-{key_id}"
        self.minted.append(
            {
                "key_id": key_id,
                "api_key": api_key,
                "tier": tier,
                "budget_usd": Decimal(budget_usd),
                "metadata": metadata,
            }
        )
        return {"key_id": key_id, "api_key": api_key}

    async def revoke_key(self, key_id: str) -> None:
        self.revoked.append(key_id)


# ---------------------------------------------------------------------------
# Scripted-result fake AsyncSession
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, *, one=None, scalar=None, scalars=None):
        self._one = one
        self._scalar = scalar
        self._scalars = scalars or []

    def one_or_none(self):
        return self._one

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        parent = self

        class _S:
            def all(self_inner):
                return list(parent._scalars)

        return _S()


class FakeDb:
    """Scripted AsyncSession. Pass a FIFO list of `_Result` objects.

    `flush` is a no-op; added rows are tracked in `.added`. Also supports
    a writable `.pending_rows` used by tests that then pop a new result
    for subsequent SELECTs.
    """

    def __init__(self, results: list[_Result]):
        self._results = list(results)
        self.added: list[Any] = []
        self.flush_count = 0

    async def execute(self, _stmt):
        if not self._results:
            return _Result(one=None, scalar=None, scalars=[])
        return self._results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flush_count += 1


def _mk_instance(state="installed", app_state="approved", hosted_agents=None):
    instance = MagicMock()
    instance.id = uuid4()
    instance.state = state
    instance.installer_user_id = uuid4()
    instance.app_version_id = uuid4()
    instance.app_id = uuid4()
    app = MagicMock()
    app.id = instance.app_id
    app.state = app_state
    version = MagicMock()
    version.id = instance.app_version_id
    version.manifest_json = (
        {"compute": {"hosted_agents": hosted_agents}} if hosted_agents is not None else {}
    )
    return instance, app, version


# ---------------------------------------------------------------------------
# hosted_agent_runtime tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_begin_hosted_invocation_agent_not_declared() -> None:
    instance, app, version = _mk_instance(hosted_agents=[{"id": "other"}])
    db = FakeDb([_Result(one=(instance, app, version))])
    with pytest.raises(AgentNotDeclaredError):
        await begin_hosted_invocation(
            db,  # type: ignore[arg-type]
            app_instance_id=instance.id,
            agent_id="missing",
            installer_user_id=uuid4(),
            delegate=FakeDelegate(),
        )


@pytest.mark.asyncio
async def test_begin_hosted_invocation_uses_invocation_tier_when_no_parent() -> None:
    instance, app, version = _mk_instance(
        hosted_agents=[
            {
                "id": "agent-a",
                "system_prompt_ref": "prompt://a",
                "model_pref": "anthropic/claude-sonnet",
                "tools_ref": ["t1"],
                "mcps_ref": [],
                "max_tokens": 1000,
            }
        ]
    )
    delegate = FakeDelegate()
    db = FakeDb([_Result(one=(instance, app, version))])
    handle = await begin_hosted_invocation(
        db,  # type: ignore[arg-type]
        app_instance_id=instance.id,
        agent_id="agent-a",
        installer_user_id=uuid4(),
        delegate=delegate,
    )
    assert handle.agent_id == "agent-a"
    assert handle.model == "anthropic/claude-sonnet"
    assert handle.tools_ref == ["t1"]
    assert handle.api_key.startswith("sk-fake-")
    assert len(delegate.minted) == 1
    assert delegate.minted[0]["tier"] == KeyTier.INVOCATION.value
    assert delegate.minted[0]["metadata"]["hosted_agent_id"] == "agent-a"


@pytest.mark.asyncio
async def test_begin_hosted_invocation_uses_nested_tier_when_parent_given() -> None:
    instance, app, version = _mk_instance(
        hosted_agents=[{"id": "agent-b", "system_prompt_ref": "p"}]
    )
    parent_session_id = uuid4()
    # Parent session key row
    parent_row = MagicMock()
    parent_row.key_id = "parent-key-1"
    parent_row.parent_key_id = None
    parent_row.tier = KeyTier.SESSION.value
    parent_row.state = KeyState.ACTIVE.value
    parent_row.budget_usd = Decimal("10.00")
    parent_row.spent_usd = Decimal("0")

    db = FakeDb(
        [
            _Result(one=(instance, app, version)),  # _load_instance_with_version
            _Result(scalar=parent_row),              # _find_parent_session_key
            _Result(scalar=parent_row),              # mint: lock parent (with_for_update)
            _Result(scalar=None),                    # mint: _compute_ancestor_chain_len walk
        ]
    )
    delegate = FakeDelegate()
    handle = await begin_hosted_invocation(
        db,  # type: ignore[arg-type]
        app_instance_id=instance.id,
        agent_id="agent-b",
        installer_user_id=uuid4(),
        delegate=delegate,
        parent_session_id=parent_session_id,
        budget_usd=Decimal("0.10"),
    )
    assert delegate.minted[0]["tier"] == KeyTier.NESTED.value
    assert handle.budget_usd == Decimal("0.10")


@pytest.mark.asyncio
async def test_list_declared_agents_empty_when_no_manifest_key() -> None:
    version = MagicMock()
    version.manifest_json = {}
    db = FakeDb([_Result(scalar=version)])
    result = await list_declared_agents(db, app_instance_id=uuid4())  # type: ignore[arg-type]
    assert result == []


@pytest.mark.asyncio
async def test_list_declared_agents_returns_list() -> None:
    version = MagicMock()
    version.manifest_json = {
        "compute": {
            "hosted_agents": [
                {"id": "a", "system_prompt_ref": "x"},
                {"id": "b", "system_prompt_ref": "y"},
            ]
        }
    }
    db = FakeDb([_Result(scalar=version)])
    result = await list_declared_agents(db, app_instance_id=uuid4())  # type: ignore[arg-type]
    assert [a["id"] for a in result] == ["a", "b"]


# ---------------------------------------------------------------------------
# warm_pool tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refill_warm_pool_mints_shortfall(monkeypatch) -> None:
    instance, app, version = _mk_instance(
        hosted_agents=[{"id": "agent-w", "warm_pool_size": 3}]
    )
    # First execute = _load_manifest_hosted_agents
    # Second execute = _count_unclaimed (returns 1 existing key)
    existing_key = "warm-existing-1"
    db = FakeDb(
        [
            _Result(one=(instance, version, app)),
            _Result(scalars=[existing_key]),
        ]
    )

    mint_calls: list[dict] = []

    async def fake_mint(_db, **kwargs):
        mint_calls.append(kwargs)
        row = MagicMock()
        row.key_id = f"new-{len(mint_calls)}"
        return row

    monkeypatch.setattr(
        "app.services.apps.warm_pool.litellm_keys.mint", fake_mint
    )

    result = await warm_pool.refill_warm_pool(
        db,  # type: ignore[arg-type]
        app_instance_id=instance.id,
        delegate=FakeDelegate(),
    )
    assert result == {"minted": 2, "existing": 1}
    assert len(mint_calls) == 2
    assert all(c["tier"] == KeyTier.INVOCATION for c in mint_calls)


@pytest.mark.asyncio
async def test_refill_warm_pool_noop_when_full(monkeypatch) -> None:
    instance, app, version = _mk_instance(
        hosted_agents=[{"id": "agent-w", "warm_pool_size": 2}]
    )
    db = FakeDb(
        [
            _Result(one=(instance, version, app)),
            _Result(scalars=["k1", "k2"]),
        ]
    )

    called = []

    async def fake_mint(_db, **kwargs):
        called.append(kwargs)
        row = MagicMock()
        row.key_id = "nope"
        return row

    monkeypatch.setattr(
        "app.services.apps.warm_pool.litellm_keys.mint", fake_mint
    )

    result = await warm_pool.refill_warm_pool(
        db,  # type: ignore[arg-type]
        app_instance_id=instance.id,
        delegate=FakeDelegate(),
    )
    assert result == {"minted": 0, "existing": 2}
    assert called == []


@pytest.mark.asyncio
async def test_claim_warm_key_returns_none_when_empty() -> None:
    db = FakeDb([_Result(scalar=None)])
    key = await warm_pool.claim_warm_key(
        db,  # type: ignore[arg-type]
        app_instance_id=uuid4(),
        agent_id="agent-w",
    )
    assert key is None
