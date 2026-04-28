"""Unit tests for ``services.automations.grant_resolver.preflight_check``.

The resolver consults two surfaces:

1. ``contract.allowed_tools`` / ``allowed_skills`` / ``allowed_mcps`` /
   ``allowed_apps`` directly off ``AutomationDefinition.contract``. No DB
   round-trip — we exercise this path with synthesized contracts.

2. The ``automation_grants`` SQL VIEW. The VIEW is Postgres-only — on
   SQLite the resolver falls back to ``REASON_VIEW_UNAVAILABLE``. The
   tests here patch ``_lookup_view_row`` (and ``_view_available``) so
   the positive / revoked code paths run without a Postgres engine.

Coverage matrix:

* user → use → mcp_server (granted via VIEW row)
* missing grant row → granted=False, reason=no_grant_row
* revoked grant (revoked_at set) → granted=False (filtered upstream by
  the VIEW's WHERE clause; tests assert on the resolver shape)
* contract.allowed_tools inline → granted=True via contract_allowlist
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Importing models registers all tables on Base.metadata.
from app import models, models_automations  # noqa: F401
from app.database import Base
from app.services.automations import grant_resolver


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Per-test SQLite engine with the full ORM schema (no FKs)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_view(monkeypatch, *, available: bool, row: dict[str, Any] | None) -> None:
    """Patch the resolver's two view helpers to return canned values.

    ``_lookup_view_row`` returns ``row`` (or None) regardless of inputs;
    ``_view_available`` returns ``available``. Together that's the entire
    DB-side surface area :func:`preflight_check` consults.
    """

    async def _fake_lookup(_db, **_kwargs):
        return row

    async def _fake_available(_db):
        return available

    monkeypatch.setattr(grant_resolver, "_lookup_view_row", _fake_lookup)
    monkeypatch.setattr(grant_resolver, "_view_available", _fake_available)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preflight_check_user_mcp_grant_via_view(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live VIEW row → granted=True with source='view_row'."""
    user_id = uuid.uuid4()
    server_id = "slack-mcp"
    fake_row = {
        "subject_kind": "user",
        "subject_id": str(user_id),
        "capability": "use",
        "resource_kind": "mcp_server",
        "resource_id": server_id,
        "constraints": {"scopes": ["chat:write"]},
        "granted_at": datetime.now(UTC),
        "revoked_at": None,
    }
    _stub_view(monkeypatch, available=True, row=fake_row)

    result = await grant_resolver.preflight_check(
        db,
        subject_kind="user",
        subject_id=user_id,
        capability="use",
        resource_kind="mcp_server",
        resource_id=server_id,
    )

    assert result.granted is True
    assert result.reason == grant_resolver.REASON_GRANTED
    assert result.source == "view_row"
    assert result.constraints == {"scopes": ["chat:write"]}


@pytest.mark.asyncio
async def test_preflight_check_missing_grant_returns_false(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No VIEW row + view IS available → granted=False, reason=no_grant_row."""
    _stub_view(monkeypatch, available=True, row=None)

    result = await grant_resolver.preflight_check(
        db,
        subject_kind="user",
        subject_id=uuid.uuid4(),
        capability="use",
        resource_kind="mcp_server",
        resource_id="discord-mcp",
    )

    assert result.granted is False
    assert result.reason == grant_resolver.REASON_NO_GRANT_ROW
    assert result.source == "none"


@pytest.mark.asyncio
async def test_preflight_check_revoked_grant_filtered(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A revoked row never makes it past the VIEW WHERE clause.

    The fake_lookup returns None to simulate the WHERE filter dropping
    the row; the resolver then surfaces ``no_grant_row``.
    """
    _stub_view(monkeypatch, available=True, row=None)

    result = await grant_resolver.preflight_check(
        db,
        subject_kind="user",
        subject_id=uuid.uuid4(),
        capability="use",
        resource_kind="mcp_server",
        resource_id="revoked-mcp",
    )

    assert result.granted is False
    assert result.reason == grant_resolver.REASON_NO_GRANT_ROW


@pytest.mark.asyncio
async def test_preflight_check_contract_allowed_tools_inline(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """contract.allowed_tools=['web_fetch'] → granted via contract_allowlist."""
    # Stub the VIEW to ensure the contract path short-circuits BEFORE the
    # VIEW is consulted (allowlist wins on the first pass).
    _stub_view(monkeypatch, available=True, row=None)

    contract = {
        "allowed_tools": ["web_fetch", "todos"],
        "max_compute_tier": 0,
    }
    result = await grant_resolver.preflight_check(
        db,
        subject_kind="automation",
        subject_id=uuid.uuid4(),
        capability="use",
        resource_kind="tool",
        resource_id="web_fetch",
        contract=contract,
    )

    assert result.granted is True
    assert result.reason == grant_resolver.REASON_GRANTED
    assert result.source == "contract_allowlist"
    assert result.constraints.get("matched_field") == "allowed_tools"

    # Same shape, but querying a tool NOT in the allowlist + nothing in
    # the VIEW → not_in_contract (the contract was provided but missed).
    miss = await grant_resolver.preflight_check(
        db,
        subject_kind="automation",
        subject_id=uuid.uuid4(),
        capability="use",
        resource_kind="tool",
        resource_id="bash_exec",
        contract=contract,
    )
    assert miss.granted is False
    assert miss.reason == grant_resolver.REASON_NOT_IN_CONTRACT
