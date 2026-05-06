"""
Wave 4 — source-aware marketplace router integration tests.

Verifies the federated-marketplace cuts in ``app.routers.marketplace`` /
``app.routers.mcp`` work end-to-end against a real Postgres test DB:

* ``?source=<handle>`` filters list endpoints to a single source.
* Omitted ``?source=`` returns rows interleaved across every active source.
* Install endpoints flow through ``services.marketplace_federation.install_guard``:
    - Tesslate Official agent install succeeds.
    - Untrusted-source MCP install → 403 with the deny reason.
    - Private-source MCP install without ``confirmed`` → 409 with the
      ``scope_tool_list`` payload the UI renders.
    - Private-source MCP install with ``confirmed=true`` → succeeds.
* Hardcoded ``"Tesslate"`` branding is replaced by the joined
  ``MarketplaceSource.display_name`` everywhere it surfaces in the response.

Test design: this test only writes data into ``marketplace_sources`` and
``marketplace_agents`` directly via the orchestrator's async session — we
do NOT need a live federation hub for these tests because everything we
exercise here lives in the orchestrator's local catalog cache.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# Stable UUIDs for the fake federated sources we insert in setup. Using
# fixed values lets us re-run the suite without pollution between tests
# (we delete-then-insert on every test that needs them).
_UNTRUSTED_SOURCE_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
_PRIVATE_SOURCE_ID = uuid.UUID("22222222-3333-4444-5555-666666666666")
_TESSLATE_OFFICIAL_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# Per-test seed: stable UUIDs for the agents pointed at by each fake source.
_UNTRUSTED_MCP_ID = uuid.UUID("33333333-4444-5555-6666-777777777777")
_PRIVATE_MCP_ID = uuid.UUID("44444444-5555-6666-7777-888888888888")
# A free tesslate-official agent we seed for the install-agent test.
_TESSLATE_AGENT_ID = uuid.UUID("55555555-6666-7777-8888-999999999999")

# Mixing the app's AsyncSessionLocal with the TestClient's own event loop
# produces "Future attached to a different loop" errors. The
# ``test_builtin_skill_guard.py`` pattern works around it by running each
# DB step on a throwaway loop with a fresh engine — we mirror the same
# approach here so the seed step can't poison the TestClient's loop.
_ASYNC_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test",
)


def _run_db(coro_fn, *args, **kwargs):
    """Run a DB coroutine on a throwaway event loop with a fresh engine.

    A new engine per call keeps asyncpg's connection pool bound to the
    loop that's about to close, avoiding cross-loop coupling with the
    FastAPI TestClient's own event loop.
    """

    async def _inner():
        engine = create_async_engine(_ASYNC_DB_URL, pool_pre_ping=False)
        try:
            session_maker = async_sessionmaker(engine, expire_on_commit=False)
            async with session_maker() as db:
                return await coro_fn(db, *args, **kwargs)
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


_FAKE_MCP_TOOL_CONFIG = {
    "transport": "stdio",
    "command": "node",
    "args": ["server.js"],
    "tools": [
        {"name": "ls", "description": "list files", "destructive": False},
        {"name": "rm", "description": "delete file", "destructive": True},
    ],
    "scopes": ["fs.read", "fs.write"],
}


async def _seed(db: AsyncSession) -> None:
    """Insert/upsert ``untrusted-test`` and ``private-test`` source rows.

    Upsert (rather than delete-then-insert) because ``user_mcp_configs``
    has a NOT NULL ``marketplace_agent_id`` column with a SET NULL
    cascade FK — deleting the agent rows from a prior run would trigger
    the cascade and immediately violate the NOT NULL.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models import MarketplaceAgent, MarketplaceSource

    # Upsert the two fake system sources by id (PK upsert).
    src_stmt = pg_insert(MarketplaceSource).values(
        [
            {
                "id": _UNTRUSTED_SOURCE_ID,
                "handle": "untrusted-test",
                "display_name": "Untrusted Test Hub",
                "base_url": "https://untrusted.example.com",
                "scope": "system",
                "trust_level": "untrusted",
                "is_active": True,
            },
            {
                "id": _PRIVATE_SOURCE_ID,
                "handle": "private-test",
                "display_name": "Private Test Hub",
                "base_url": "https://private.example.com",
                "scope": "system",
                "trust_level": "private",
                "is_active": True,
            },
        ]
    )
    src_stmt = src_stmt.on_conflict_do_update(
        index_elements=[MarketplaceSource.id],
        set_={
            "handle": src_stmt.excluded.handle,
            "display_name": src_stmt.excluded.display_name,
            "base_url": src_stmt.excluded.base_url,
            "trust_level": src_stmt.excluded.trust_level,
            "is_active": True,
        },
    )
    await db.execute(src_stmt)

    # Upsert one MCP server per fake source. We pin the slug so re-runs
    # are deterministic without colliding with prior rows.
    for mcp_id, source_id, prefix in (
        (_UNTRUSTED_MCP_ID, _UNTRUSTED_SOURCE_ID, "untrusted"),
        (_PRIVATE_MCP_ID, _PRIVATE_SOURCE_ID, "private"),
    ):
        slug = f"{prefix}-mcp-test"
        agent_stmt = pg_insert(MarketplaceAgent).values(
            id=mcp_id,
            name=f"{prefix}-mcp-test",
            slug=slug,
            description=f"{prefix} MCP server for tests",
            category="general",
            item_type="mcp_server",
            pricing_type="free",
            price=0,
            is_active=True,
            is_published=True,
            is_system=False,
            is_builtin=False,
            source_id=source_id,
            config=_FAKE_MCP_TOOL_CONFIG,
        )
        agent_stmt = agent_stmt.on_conflict_do_update(
            index_elements=[MarketplaceAgent.id],
            set_={
                "name": agent_stmt.excluded.name,
                "slug": agent_stmt.excluded.slug,
                "description": agent_stmt.excluded.description,
                "category": agent_stmt.excluded.category,
                "item_type": agent_stmt.excluded.item_type,
                "pricing_type": agent_stmt.excluded.pricing_type,
                "is_active": True,
                "is_published": True,
                "source_id": source_id,
                "config": _FAKE_MCP_TOOL_CONFIG,
            },
        )
        await db.execute(agent_stmt)

    # Wipe any user_mcp_configs that target our fake MCPs so each test
    # starts with a clean install slate (otherwise the second run would
    # short-circuit on existing-row detection).
    from app.models import UserMcpConfig

    await db.execute(
        delete(UserMcpConfig).where(
            UserMcpConfig.marketplace_agent_id.in_([_UNTRUSTED_MCP_ID, _PRIVATE_MCP_ID])
        )
    )

    # Also seed a free Tesslate Official agent so the install-agent /
    # creator-name / source-metadata tests have something to assert on.
    # On a fresh test DB the seed pipeline may not have run, so we plant
    # a deterministic row pinned to the seeded tesslate-official source.
    tess_agent_stmt = pg_insert(MarketplaceAgent).values(
        id=_TESSLATE_AGENT_ID,
        name="Tesslate Wave-4 Test Agent",
        slug="tesslate-wave4-test-agent",
        description="Free agent used by the Wave 4 source-aware test.",
        category="general",
        item_type="agent",
        pricing_type="free",
        price=0,
        is_active=True,
        is_published=True,
        is_system=False,
        is_builtin=False,
        source_id=_TESSLATE_OFFICIAL_ID,
    )
    tess_agent_stmt = tess_agent_stmt.on_conflict_do_update(
        index_elements=[MarketplaceAgent.id],
        set_={
            "name": tess_agent_stmt.excluded.name,
            "slug": tess_agent_stmt.excluded.slug,
            "is_active": True,
            "is_published": True,
            "source_id": _TESSLATE_OFFICIAL_ID,
        },
    )
    await db.execute(tess_agent_stmt)

    await db.commit()


def _seed_fake_sources_sync() -> None:
    """Synchronous wrapper around :func:`_seed` for use inside tests."""
    _run_db(_seed)


# ---------------------------------------------------------------------------
# List endpoint source filtering
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_list_agents_with_source_filter_returns_only_that_source(authenticated_client):
    """``?source=tesslate-official`` restricts the agent list to that hub."""
    client, _ = authenticated_client

    resp = client.get("/api/marketplace/agents?source=tesslate-official")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "agents" in data
    # Every returned agent must carry the requested source handle (or no
    # handle if it pre-dates Wave-1 backfill — but those don't exist on a
    # fresh test DB).
    for agent in data["agents"]:
        assert agent["source_handle"] in (None, "tesslate-official"), (
            f"Agent {agent.get('slug')} returned with source_handle="
            f"{agent.get('source_handle')!r} when filter was tesslate-official"
        )


@pytest.mark.integration
def test_list_agents_without_source_filter_returns_all(authenticated_client):
    """No ``?source=`` returns rows from every active source interleaved."""
    client, _ = authenticated_client

    resp = client.get("/api/marketplace/agents")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "agents" in data
    # Result set should be a superset of (or equal to) the
    # tesslate-official-only result.
    filtered = client.get("/api/marketplace/agents?source=tesslate-official").json()
    assert len(data["agents"]) >= len(filtered["agents"])


@pytest.mark.integration
def test_list_agents_unknown_source_returns_404(authenticated_client):
    client, _ = authenticated_client

    resp = client.get("/api/marketplace/agents?source=does-not-exist")
    assert resp.status_code == 404
    assert "does-not-exist" in resp.text


@pytest.mark.integration
def test_list_skills_with_source_filter(authenticated_client):
    client, _ = authenticated_client
    resp = client.get("/api/marketplace/skills?source=tesslate-official")
    assert resp.status_code == 200, resp.text
    for skill in resp.json().get("skills", []):
        assert skill["source_handle"] in (None, "tesslate-official")


@pytest.mark.integration
def test_list_mcp_servers_with_source_filter(authenticated_client):
    client, _ = authenticated_client
    resp = client.get("/api/marketplace/mcp-servers?source=tesslate-official")
    assert resp.status_code == 200, resp.text
    for srv in resp.json().get("mcp_servers", []):
        assert srv["source_handle"] in (None, "tesslate-official")


@pytest.mark.integration
def test_list_themes_with_source_filter(authenticated_client):
    client, _ = authenticated_client
    resp = client.get("/api/marketplace/themes?source=tesslate-official")
    assert resp.status_code == 200, resp.text
    for theme in resp.json().get("items", []):
        assert theme["source_handle"] in (None, "tesslate-official")


# ---------------------------------------------------------------------------
# "Tesslate" → display_name replacement
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_creator_name_uses_source_display_name(authenticated_client):
    """Verify the seeded source's ``display_name`` shows up in the response.

    The legacy router hardcoded ``"Tesslate"`` for every official-row
    creator name. After Wave 4 the value is the joined
    ``MarketplaceSource.display_name``; the seeded Tesslate Official row
    has ``display_name="Tesslate Official"``.
    """
    _seed_fake_sources_sync()  # also seeds the tesslate-official test agent
    client, _ = authenticated_client
    resp = client.get("/api/marketplace/agents?source=tesslate-official")
    assert resp.status_code == 200, resp.text
    agents = resp.json().get("agents", [])
    assert agents, "Expected at least the seeded tesslate-official agent"
    # Find at least one official-sourced row and assert the new label.
    official_rows = [
        a for a in agents if a.get("creator_type") == "official"
    ]
    assert official_rows, "Expected at least one official-creator agent row"
    creator_names = {a["creator_name"] for a in official_rows}
    # The seed sets display_name="Tesslate Official" exactly. The legacy
    # hardcode would have given us "Tesslate" — that's the regression we
    # want to lock down.
    assert any("Tesslate Official" in name for name in creator_names), (
        f"Expected at least one official row with creator_name 'Tesslate Official', "
        f"got {creator_names!r}"
    )


# ---------------------------------------------------------------------------
# install_guard wiring
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_install_agent_from_tesslate_official_succeeds(authenticated_client):
    """Tesslate Official is ``trust_level='official'`` → all installs allowed."""
    _seed_fake_sources_sync()  # plants the tesslate-official test agent
    client, _ = authenticated_client

    resp = client.post(f"/api/marketplace/agents/{_TESSLATE_AGENT_ID}/purchase")
    # Either succeeded (201/200) or already in library (200). install_guard
    # MUST NOT 403/409 — Tesslate Official is the always-allowed source.
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "agent_id" in body or "message" in body


@pytest.mark.integration
def test_install_mcp_from_untrusted_source_returns_403(authenticated_client):
    """``trust_level='untrusted'`` blocks ``mcp_server`` installs outright."""
    _seed_fake_sources_sync()

    client, _ = authenticated_client
    resp = client.post(
        "/api/mcp/install",
        json={
            "marketplace_agent_id": str(_UNTRUSTED_MCP_ID),
            "credentials": {},
            "scope_level": "user",
        },
    )
    assert resp.status_code == 403, resp.text
    detail = resp.json().get("detail")
    assert isinstance(detail, dict), f"Expected dict detail, got {detail!r}"
    assert detail.get("error") == "install_blocked"
    assert "untrusted" in detail.get("reason", "")
    assert detail.get("kind") == "mcp_server"


@pytest.mark.integration
def test_install_mcp_from_private_source_without_confirmation_returns_409(
    authenticated_client,
):
    """``trust_level='private'`` requires explicit per-install confirmation.

    The 409 carries the ``scope_tool_list`` + ``destructive_tools`` so the
    UI can render the permission prompt. Tools marked ``destructive=True``
    in the manifest must surface in the destructive-tool list.
    """
    _seed_fake_sources_sync()

    client, _ = authenticated_client
    resp = client.post(
        "/api/mcp/install",
        json={
            "marketplace_agent_id": str(_PRIVATE_MCP_ID),
            "credentials": {},
            "scope_level": "user",
            "confirmed": False,
        },
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json().get("detail")
    assert isinstance(detail, dict), f"Expected dict detail, got {detail!r}"
    assert detail.get("error") == "install_requires_confirmation"
    assert detail.get("kind") == "mcp_server"
    # The seeded fake mcp_server config declares "rm" as destructive.
    destructive = detail.get("destructive_tools") or []
    assert "rm" in destructive, f"Expected rm in destructive_tools, got {destructive!r}"
    # scope_tool_list should be a non-empty list with both "ls" and "rm".
    scope_tool_list = detail.get("scope_tool_list") or []
    tool_names = {t.get("name") for t in scope_tool_list if isinstance(t, dict)}
    assert {"ls", "rm"}.issubset(tool_names), (
        f"Expected ls and rm in scope_tool_list, got {tool_names!r}"
    )
    # The UI-facing prompt block carries transport / command / scopes.
    prompt = detail.get("prompt") or {}
    assert prompt.get("transport") == "stdio"
    assert prompt.get("command") == "node"
    assert "fs.read" in (prompt.get("scope_list") or [])


@pytest.mark.integration
def test_install_mcp_from_private_source_with_confirmation_proceeds(
    authenticated_client,
):
    """With ``confirmed=true`` the ``private`` install gate clears.

    The install may still error later in the flow (the static-credential
    flow tries to test-connect to the bogus stdio command), but the
    important assertion is that install_guard does NOT 403/409 — anything
    other than 403 install_blocked / 409 install_requires_confirmation is
    a pass for this test.
    """
    _seed_fake_sources_sync()

    client, _ = authenticated_client
    resp = client.post(
        "/api/mcp/install",
        json={
            "marketplace_agent_id": str(_PRIVATE_MCP_ID),
            "credentials": {},
            "scope_level": "user",
            "confirmed": True,
        },
    )
    # The install path may succeed (201) or fail with a non-guard error
    # (e.g. 500 from the test-connect; we only care that install_guard
    # didn't reject the call).
    if resp.status_code in (403, 409):
        detail = resp.json().get("detail")
        assert not (
            isinstance(detail, dict)
            and detail.get("error")
            in ("install_blocked", "install_requires_confirmation")
        ), f"install_guard rejected confirmed install: {detail!r}"
    # Any other outcome (201 success, 400 schema, 500 test-connect) is OK.


# ---------------------------------------------------------------------------
# Read paths surface source_handle / source_trust_level on items
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_agent_response_includes_source_metadata(authenticated_client):
    _seed_fake_sources_sync()
    client, _ = authenticated_client
    resp = client.get("/api/marketplace/agents?source=tesslate-official&limit=10")
    assert resp.status_code == 200, resp.text
    agents = resp.json().get("agents", [])
    assert agents, "Expected at least the seeded tesslate-official agent"
    agent = next((a for a in agents if a["source_handle"] == "tesslate-official"), agents[0])
    # New Wave-4 fields: every browse row exposes the source it was
    # synced from so the frontend can render the source chip.
    assert "source_handle" in agent
    assert "source_trust_level" in agent
    if agent["source_handle"] == "tesslate-official":
        assert agent["source_trust_level"] == "official"
