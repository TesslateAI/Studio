"""
Unit tests for ``app.services.marketplace_federation``.

Covers:
  - install_guard for every (trust_level, kind) cell of the matrix.
  - dispatch_purchase for the four routing rules.
  - mcp_install_prompt parsing tolerance + destructive-tool extraction.
  - live_resolve auto-pinning behaviour at install time (Wave 3 fix).
  - list_cached_items / get_cached_item read paths used by Wave 4 routers.

The install_guard / dispatch_purchase / mcp_install_prompt tests are
pure-Python with no DB. The live_resolve and cached-read tests use the
shared orchestrator test DB (Postgres on :5433) and the seeded
``tesslate-official`` source row.
"""

from __future__ import annotations

import os
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import (
    MarketplaceAgent,
    MarketplaceSource,
)
from app.services.marketplace_federation import (
    InstallGuardResult,
    PurchaseRoute,
    ResolvedItem,
    dispatch_purchase,
    get_cached_item,
    install_guard,
    list_cached_items,
    live_resolve,
    mcp_install_prompt,
)


# ---------------------------------------------------------------------------
# install_guard matrix
# ---------------------------------------------------------------------------


def _make_source(
    *,
    trust_level: str,
    scope: str = "system",
    user_id=None,
    team_id=None,
    is_active: bool = True,
    capabilities: list[str] | None = None,
):
    """Build a duck-typed source row that matches the attribute access in
    install_guard / dispatch_purchase. We avoid SQLAlchemy here to keep
    these tests DB-free."""
    return SimpleNamespace(
        id=uuid4(),
        handle=f"{trust_level}-source",
        base_url="https://example.com",
        trust_level=trust_level,
        scope=scope,
        user_id=user_id,
        team_id=team_id,
        is_active=is_active,
        capabilities_cache=capabilities or [],
        pinned_hub_id="hub-test",
    )


_NON_APP_NON_MCP_KINDS = ["agent", "skill", "theme", "base", "workflow_template"]
_RESTRICTED_KINDS = ["mcp_server", "app"]


@pytest.mark.parametrize("trust_level", ["official", "admin_trusted"])
@pytest.mark.parametrize("kind", _NON_APP_NON_MCP_KINDS + _RESTRICTED_KINDS)
def test_install_guard_trusted_allows_all_kinds(trust_level: str, kind: str) -> None:
    source = _make_source(trust_level=trust_level)
    result = install_guard(source, kind)
    assert result.allowed is True
    assert result.requires_confirmation is False
    assert result.reason == "trusted_source"


@pytest.mark.parametrize("kind", _NON_APP_NON_MCP_KINDS)
def test_install_guard_untrusted_allows_safe_kinds(kind: str) -> None:
    source = _make_source(trust_level="untrusted")
    result = install_guard(source, kind)
    assert result.allowed is True
    assert result.requires_confirmation is False


@pytest.mark.parametrize("kind", _RESTRICTED_KINDS)
def test_install_guard_untrusted_blocks_restricted_kinds(kind: str) -> None:
    source = _make_source(trust_level="untrusted")
    result = install_guard(source, kind)
    assert result.allowed is False
    assert result.reason == f"untrusted_blocks_{kind}"


@pytest.mark.parametrize("kind", _NON_APP_NON_MCP_KINDS)
def test_install_guard_private_allows_safe_kinds_no_confirmation(kind: str) -> None:
    source = _make_source(trust_level="private")
    result = install_guard(source, kind)
    assert result.allowed is True
    assert result.requires_confirmation is False
    assert result.scope_tool_list is None


def test_install_guard_private_mcp_server_requires_confirmation_and_extracts_tools() -> None:
    source = _make_source(trust_level="private")
    manifest = {
        "manifest": {
            "transport": "stdio",
            "command": "node",
            "args": ["server.js"],
            "tools": [
                {"name": "list_files", "description": "ls"},
                {"name": "delete_file", "description": "rm", "destructive": True},
            ],
            "scopes": ["fs.read", "fs.write"],
        }
    }
    result = install_guard(source, "mcp_server", version_meta=manifest)
    assert result.allowed is True
    assert result.requires_confirmation is True
    assert result.reason == "private_requires_confirmation:mcp_server"
    assert result.scope_tool_list is not None
    assert {t["name"] for t in result.scope_tool_list} == {"list_files", "delete_file"}
    assert "delete_file" in result.destructive_tools


def test_install_guard_private_app_requires_confirmation_with_action_surface() -> None:
    source = _make_source(trust_level="private")
    manifest = {
        "manifest": {
            "actions": [
                {"name": "send_email", "description": "send", "billing": "per_invocation"},
                {"name": "drop_table", "description": "delete db", "destructive": True},
            ],
        }
    }
    result = install_guard(source, "app", version_meta=manifest)
    assert result.allowed is True
    assert result.requires_confirmation is True
    assert result.reason == "private_requires_confirmation:app"
    assert result.scope_tool_list is not None
    names = {a["name"] for a in result.scope_tool_list}
    assert names == {"send_email", "drop_table"}
    assert "drop_table" in result.destructive_tools


@pytest.mark.parametrize("kind", _NON_APP_NON_MCP_KINDS + _RESTRICTED_KINDS)
def test_install_guard_local_system_allows_all(kind: str) -> None:
    source = _make_source(trust_level="local", scope="system")
    result = install_guard(source, kind)
    assert result.allowed is True
    assert result.reason == "local_system"


def test_install_guard_local_user_owner_required() -> None:
    owner_id = uuid4()
    source = _make_source(trust_level="local", scope="user", user_id=owner_id)
    # Wrong requester
    other = uuid4()
    denied = install_guard(source, "agent", requester_user_id=other)
    assert denied.allowed is False
    assert denied.reason == "local_user_owner_mismatch"
    # Correct requester
    allowed = install_guard(source, "agent", requester_user_id=owner_id)
    assert allowed.allowed is True
    assert allowed.reason == "local_user_owner"


def test_install_guard_local_team_returns_owner_check_required() -> None:
    team_id = uuid4()
    source = _make_source(trust_level="local", scope="team", team_id=team_id)
    result = install_guard(source, "agent")
    assert result.allowed is True
    assert result.reason == "local_team_owner_check_required"


def test_install_guard_inactive_source_blocks_install() -> None:
    source = _make_source(trust_level="official", is_active=False)
    result = install_guard(source, "agent")
    assert result.allowed is False
    assert result.reason == "source_inactive"


def test_install_guard_unknown_kind_fails_closed() -> None:
    source = _make_source(trust_level="official")
    result = install_guard(source, "totally_made_up_kind")
    assert result.allowed is False
    assert "unknown_kind" in result.reason


def test_install_guard_unknown_trust_level_fails_closed() -> None:
    source = _make_source(trust_level="hijacked-by-attacker")
    result = install_guard(source, "agent")
    assert result.allowed is False
    assert result.reason.startswith("unknown_trust:")


# ---------------------------------------------------------------------------
# dispatch_purchase routing rules
# ---------------------------------------------------------------------------


def test_dispatch_purchase_free_item_routes_free() -> None:
    source = _make_source(trust_level="official")
    item = {
        "kind": "agent",
        "slug": "free-agent",
        "pricing": {"pricing_type": "free", "price_cents": 0},
    }
    routing = dispatch_purchase(source, item)
    assert routing.route is PurchaseRoute.FREE


def test_dispatch_purchase_official_paid_routes_orchestrator_stripe() -> None:
    source = _make_source(trust_level="official")
    item = {
        "kind": "agent",
        "slug": "paid-agent",
        "pricing": {
            "pricing_type": "paid",
            "price_cents": 1000,
            "stripe_price_id": "price_OFFICIAL_123",
        },
    }
    routing = dispatch_purchase(source, item)
    assert routing.route is PurchaseRoute.ORCHESTRATOR_STRIPE
    assert routing.stripe_price_id == "price_OFFICIAL_123"


def test_dispatch_purchase_untrusted_paid_refuses() -> None:
    source = _make_source(trust_level="untrusted", capabilities=["catalog.read"])
    item = {
        "kind": "agent",
        "slug": "rogue-paid",
        "pricing": {"pricing_type": "paid", "price_cents": 999, "stripe_price_id": "x"},
    }
    routing = dispatch_purchase(source, item)
    assert routing.route is PurchaseRoute.REFUSE
    assert routing.refuse_reason == "pricing_not_supported"


def test_dispatch_purchase_private_paid_refuses() -> None:
    source = _make_source(trust_level="private", capabilities=["catalog.read"])
    item = {
        "kind": "agent",
        "slug": "p1",
        "pricing": {"pricing_type": "paid", "price_cents": 500, "stripe_price_id": "x"},
    }
    routing = dispatch_purchase(source, item)
    assert routing.route is PurchaseRoute.REFUSE
    assert routing.refuse_reason == "pricing_not_supported"


def test_dispatch_purchase_admin_trusted_with_hub_checkout_capability_but_flag_off() -> None:
    """Wave-3 default: feature flag is OFF, so even an admin_trusted hub
    that advertises pricing.checkout still routes via Stripe / refuse.

    Wave 9 will flip the flag — Wave 3 must *not* leak the route while the
    flag is off."""
    source = _make_source(
        trust_level="admin_trusted",
        capabilities=["catalog.read", "pricing.read", "pricing.checkout"],
    )
    item = {
        "kind": "agent",
        "slug": "p2",
        "pricing": {"pricing_type": "paid", "price_cents": 500},
    }
    routing = dispatch_purchase(source, item)
    # admin_trusted has no orchestrator-Stripe path, no flag → refuse.
    assert routing.route is PurchaseRoute.REFUSE


def test_dispatch_purchase_admin_trusted_hub_checkout_when_flag_on(monkeypatch) -> None:
    # Force the flag on for this test.
    from app.services import marketplace_federation as facade

    monkeypatch.setattr(facade, "hub_checkout_enabled", lambda: True)

    source = _make_source(
        trust_level="admin_trusted",
        capabilities=["catalog.read", "pricing.read", "pricing.checkout"],
    )
    item = {
        "kind": "agent",
        "slug": "p3",
        "pricing": {"pricing_type": "paid", "price_cents": 500},
    }
    routing = dispatch_purchase(source, item)
    assert routing.route is PurchaseRoute.HUB_CHECKOUT
    assert routing.hub_kind == "agent"
    assert routing.hub_slug == "p3"


def test_dispatch_purchase_official_with_hub_checkout_flag_on_prefers_hub(monkeypatch) -> None:
    from app.services import marketplace_federation as facade

    monkeypatch.setattr(facade, "hub_checkout_enabled", lambda: True)
    source = _make_source(
        trust_level="official",
        capabilities=["catalog.read", "pricing.read", "pricing.checkout"],
    )
    item = {
        "kind": "agent",
        "slug": "p4",
        "pricing": {
            "pricing_type": "paid",
            "price_cents": 500,
            "stripe_price_id": "price_FALLBACK",
        },
    }
    routing = dispatch_purchase(source, item)
    # Hub checkout wins per priority rules.
    assert routing.route is PurchaseRoute.HUB_CHECKOUT


# ---------------------------------------------------------------------------
# mcp_install_prompt parsing
# ---------------------------------------------------------------------------


def test_mcp_install_prompt_parses_full_manifest() -> None:
    manifest = {
        "transport": "stdio",
        "command": "node",
        "args": ["dist/server.js", "--quiet"],
        "env": {"OPENAI_API_KEY": "${env.OPENAI_API_KEY}"},
        "tools": [
            {"name": "search_docs", "description": "search"},
            {"name": "delete_repo", "description": "destroy", "destructive": True},
        ],
        "scopes": ["repo.read", "repo.write"],
    }
    prompt = mcp_install_prompt(manifest)
    assert prompt.transport == "stdio"
    assert prompt.command == "node"
    assert prompt.args == ["dist/server.js", "--quiet"]
    assert "OPENAI_API_KEY" in prompt.env_keys
    assert prompt.scope_list == ["repo.read", "repo.write"]
    assert {t["name"] for t in prompt.tool_list} == {"search_docs", "delete_repo"}
    assert prompt.destructive_tools == ["delete_repo"]


def test_mcp_install_prompt_infers_transport_from_shape() -> None:
    # No explicit transport — infer from URL presence.
    prompt = mcp_install_prompt({"url": "https://mcp.example.com"})
    assert prompt.transport == "http"
    assert prompt.url == "https://mcp.example.com"


def test_mcp_install_prompt_handles_nested_server_block() -> None:
    manifest = {"server": {"transport": "websocket", "url": "wss://mcp"}}
    prompt = mcp_install_prompt(manifest)
    assert prompt.transport == "websocket"
    assert prompt.url == "wss://mcp"


def test_mcp_install_prompt_tolerates_garbage_input() -> None:
    prompt = mcp_install_prompt({})  # empty manifest
    assert prompt.transport is None
    assert prompt.tool_list == []
    assert prompt.destructive_tools == []


# ---------------------------------------------------------------------------
# DB-backed tests for live_resolve auto-pin + cache read helpers (Wave 3+4)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine(
        "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test",
        future=True,
    )
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionFactory() as session:
        yield session
    await engine.dispose()


class _FakeResolveClient:
    """Fakes the subset of ``MarketplaceClient`` that ``live_resolve`` calls.

    Each method returns whatever envelope the test wired up at construction
    time. Records call counts so tests can assert e.g. ``get_manifest`` was
    invoked exactly once on the auto-pin path.
    """

    def __init__(
        self,
        *,
        manifest: dict | None = None,
        item: dict | None = None,
        version_obj: dict | None = None,
        bundle: dict | None = None,
    ) -> None:
        self._manifest = manifest or {
            "hub_id": "fresh-hub-id",
            "capabilities": ["catalog.read", "catalog.changes"],
            "policies": {"max_bundle_bytes": 5_000_000},
        }
        self._item = item or {"slug": "x", "kind": "agent", "latest_version": "1.0.0"}
        self._version_obj = version_obj or {"version": "1.0.0", "manifest": {}}
        self._bundle = bundle
        self.manifest_calls = 0
        self.item_calls = 0
        self.version_calls = 0
        self.bundle_calls = 0
        self.aclose_calls = 0

    async def get_manifest(self):
        self.manifest_calls += 1
        return self._manifest

    async def get_item(self, kind, slug):
        self.item_calls += 1
        return self._item

    async def get_version(self, kind, slug, version):
        self.version_calls += 1
        return self._version_obj

    async def get_bundle(self, kind, slug, version):
        self.bundle_calls += 1
        if self._bundle is None:
            raise RuntimeError("bundle not advertised")
        return self._bundle

    async def list_versions(self, kind, slug):
        return [{"version": "1.0.0"}]

    async def aclose(self):
        self.aclose_calls += 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_resolve_auto_pins_unpinned_source(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unpinned source MUST get pinned before any install fetch lands.

    Pre-fix, ``live_resolve`` constructed a client with
    ``pinned_hub_id=None``, meaning the client could not enforce hub-id
    drift on subsequent calls — a brand-new source would silently install
    against whatever hub_id the URL happened to return on first contact.

    Fix: when pin is None we fetch ``/v1/manifest`` first, snapshot the
    hub_id + capabilities + policies, commit, and only then proceed with
    the actual item/version fetch using a re-bound client that enforces
    the now-pinned hub id.
    """
    handle = f"unpinned-{os.getpid()}-{int(time.time() * 1000) % 10_000_000}"
    source = MarketplaceSource(
        handle=handle,
        display_name="Unpinned Hub",
        base_url="https://example.invalid",
        scope="system",
        trust_level="untrusted",
        is_active=True,
        pinned_hub_id=None,
    )
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)

    fake = _FakeResolveClient()
    # The federation module re-constructs a client after pinning. Patch
    # MarketplaceClient at the module level so the re-bind also returns a
    # fake — otherwise the second client would try to make real HTTP calls.
    constructed: list[_FakeResolveClient] = []

    def _factory(*args, **kwargs):
        c = _FakeResolveClient()
        constructed.append(c)
        return c

    from app.services import marketplace_federation as facade

    monkeypatch.setattr(facade, "MarketplaceClient", _factory)

    try:
        result = await live_resolve(
            source,
            "agent",
            "x",
            client=fake,  # caller-provided client used for the manifest fetch
            db=db_session,
        )

        # Auto-pin happened.
        assert fake.manifest_calls == 1, (
            "live_resolve must call get_manifest exactly once when source is unpinned"
        )
        await db_session.refresh(source)
        assert source.pinned_hub_id == "fresh-hub-id"
        assert source.capabilities_cache == ["catalog.read", "catalog.changes"]
        assert source.policies_cache == {"max_bundle_bytes": 5_000_000}

        # The original client was closed and a new one re-bound to the pin.
        assert fake.aclose_calls == 1
        assert len(constructed) >= 1, "expected re-bind after auto-pin"

        # The actual install resolution proceeded against the new client.
        assert isinstance(result, ResolvedItem)
        assert result.slug == "x"
        assert result.version == "1.0.0"
    finally:
        await db_session.delete(source)
        await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_resolve_skips_manifest_when_already_pinned(
    db_session: AsyncSession,
) -> None:
    """When pin is already set, live_resolve must NOT re-fetch the manifest.

    Re-pinning on every install would defeat the whole point of pinning
    (the point is to lock in the hub_id at first contact and detect
    drift on every subsequent call).
    """
    handle = f"prepinned-{os.getpid()}-{int(time.time() * 1000) % 10_000_000}"
    source = MarketplaceSource(
        handle=handle,
        display_name="Pre-pinned Hub",
        base_url="https://example.invalid",
        scope="system",
        trust_level="untrusted",
        is_active=True,
        pinned_hub_id="locked-hub-id",
    )
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)

    fake = _FakeResolveClient()

    try:
        await live_resolve(source, "agent", "x", client=fake, db=db_session)
        assert fake.manifest_calls == 0, (
            "must not re-fetch manifest on already-pinned source"
        )
        await db_session.refresh(source)
        assert source.pinned_hub_id == "locked-hub-id"
    finally:
        await db_session.delete(source)
        await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_resolve_refuses_unpinned_source_without_db(
    db_session: AsyncSession,
) -> None:
    """If caller passes no ``db`` for an unpinned source we MUST raise rather
    than silently install — the alternative is an un-verifiable hub.
    """
    handle = f"nodb-{os.getpid()}-{int(time.time() * 1000) % 10_000_000}"
    source = MarketplaceSource(
        handle=handle,
        display_name="No-DB Hub",
        base_url="https://example.invalid",
        scope="system",
        trust_level="untrusted",
        is_active=True,
        pinned_hub_id=None,
    )
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)

    fake = _FakeResolveClient()

    try:
        with pytest.raises(ValueError, match="unpinned"):
            await live_resolve(source, "agent", "x", client=fake, db=None)
    finally:
        await db_session.delete(source)
        await db_session.commit()


# ---------------------------------------------------------------------------
# Wave 4 cache read helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def two_federated_sources(db_session: AsyncSession) -> tuple[MarketplaceSource, MarketplaceSource]:
    """Spin up two federated sources with disjoint catalog rows for the
    cross-source-filter assertions."""
    suffix = f"{os.getpid()}-{int(time.time() * 1000) % 10_000_000}"
    s1 = MarketplaceSource(
        handle=f"fed-a-{suffix}",
        display_name="Fed A",
        base_url="https://a.invalid",
        scope="system",
        trust_level="admin_trusted",
        is_active=True,
        pinned_hub_id="hub-a",
    )
    s2 = MarketplaceSource(
        handle=f"fed-b-{suffix}",
        display_name="Fed B",
        base_url="https://b.invalid",
        scope="system",
        trust_level="admin_trusted",
        is_active=True,
        pinned_hub_id="hub-b",
    )
    db_session.add_all([s1, s2])
    await db_session.commit()
    await db_session.refresh(s1)
    await db_session.refresh(s2)

    yield s1, s2

    # Teardown — delete agents first to avoid FK violations.
    await db_session.execute(
        MarketplaceAgent.__table__.delete().where(
            MarketplaceAgent.source_id.in_((s1.id, s2.id))
        )
    )
    await db_session.delete(s1)
    await db_session.delete(s2)
    await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_cached_items_filters_by_source_handle(
    db_session: AsyncSession,
    two_federated_sources: tuple[MarketplaceSource, MarketplaceSource],
) -> None:
    s1, s2 = two_federated_sources
    suffix = uuid4().hex[:10]
    rows = [
        MarketplaceAgent(
            slug=f"a-agent-1-{suffix}",
            name="A1",
            description="x",
            category="utility",
            item_type="agent",
            pricing_type="free",
            source_id=s1.id,
            source_etag="v1",
            source_remote_id="r1",
            is_active=True,
            deleted_upstream=False,
        ),
        MarketplaceAgent(
            slug=f"a-agent-2-{suffix}",
            name="A2",
            description="x",
            category="utility",
            item_type="agent",
            pricing_type="free",
            source_id=s1.id,
            source_etag="v1",
            source_remote_id="r2",
            is_active=True,
            deleted_upstream=False,
        ),
        MarketplaceAgent(
            slug=f"b-agent-1-{suffix}",
            name="B1",
            description="x",
            category="utility",
            item_type="agent",
            pricing_type="free",
            source_id=s2.id,
            source_etag="v1",
            source_remote_id="r3",
            is_active=True,
            deleted_upstream=False,
        ),
    ]
    db_session.add_all(rows)
    await db_session.commit()

    only_a = await list_cached_items(
        db_session, kind="agent", source_handle=s1.handle, limit=100
    )
    only_a_slugs = {r.slug for r in only_a}
    assert {f"a-agent-1-{suffix}", f"a-agent-2-{suffix}"} <= only_a_slugs
    assert f"b-agent-1-{suffix}" not in only_a_slugs

    only_b = await list_cached_items(
        db_session, kind="agent", source_handle=s2.handle, limit=100
    )
    only_b_slugs = {r.slug for r in only_b}
    assert f"b-agent-1-{suffix}" in only_b_slugs
    assert f"a-agent-1-{suffix}" not in only_b_slugs


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_cached_items_excludes_deleted_upstream_by_default(
    db_session: AsyncSession,
    two_federated_sources: tuple[MarketplaceSource, MarketplaceSource],
) -> None:
    s1, _ = two_federated_sources
    suffix = uuid4().hex[:10]
    live_slug = f"live-{suffix}"
    tomb_slug = f"tomb-{suffix}"
    rows = [
        MarketplaceAgent(
            slug=live_slug,
            name="Live",
            description="x",
            category="utility",
            item_type="agent",
            pricing_type="free",
            source_id=s1.id,
            source_etag="v1",
            source_remote_id="r-live",
            is_active=True,
            deleted_upstream=False,
        ),
        MarketplaceAgent(
            slug=tomb_slug,
            name="Tomb",
            description="x",
            category="utility",
            item_type="agent",
            pricing_type="free",
            source_id=s1.id,
            source_etag="v1",
            source_remote_id="r-tomb",
            is_active=False,
            deleted_upstream=True,
        ),
    ]
    db_session.add_all(rows)
    await db_session.commit()

    default = await list_cached_items(
        db_session, kind="agent", source_handle=s1.handle, limit=100
    )
    slugs = {r.slug for r in default}
    assert live_slug in slugs
    assert tomb_slug not in slugs, "deleted_upstream rows must be hidden by default"

    with_tombs = await list_cached_items(
        db_session,
        kind="agent",
        source_handle=s1.handle,
        include_deleted_upstream=True,
        include_inactive=True,
        limit=100,
    )
    with_tomb_slugs = {r.slug for r in with_tombs}
    assert tomb_slug in with_tomb_slugs


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_cached_item_returns_row_or_none(
    db_session: AsyncSession,
    two_federated_sources: tuple[MarketplaceSource, MarketplaceSource],
) -> None:
    s1, _ = two_federated_sources
    suffix = uuid4().hex[:10]
    target_slug = f"target-{suffix}"
    other_slug = f"other-{suffix}"
    rows = [
        MarketplaceAgent(
            slug=target_slug,
            name="Target",
            description="x",
            category="utility",
            item_type="agent",
            pricing_type="free",
            source_id=s1.id,
            source_etag="v1",
            source_remote_id="r-target",
            is_active=True,
            deleted_upstream=False,
        ),
        MarketplaceAgent(
            slug=other_slug,
            name="Other",
            description="x",
            category="utility",
            item_type="agent",
            pricing_type="free",
            source_id=s1.id,
            source_etag="v1",
            source_remote_id="r-other",
            is_active=True,
            deleted_upstream=False,
        ),
    ]
    db_session.add_all(rows)
    await db_session.commit()

    hit = await get_cached_item(
        db_session, source_handle=s1.handle, kind="agent", slug=target_slug
    )
    assert hit is not None
    assert hit.slug == target_slug

    miss = await get_cached_item(
        db_session, source_handle=s1.handle, kind="agent", slug=f"missing-{suffix}"
    )
    assert miss is None


@pytest.mark.asyncio
async def test_list_cached_items_unknown_kind_raises() -> None:
    """Unknown kinds must raise rather than silently returning [] — the
    caller almost certainly has a typo and we want it loud at the seam.
    The validation fires before any query so the session is unused.
    """
    with pytest.raises(ValueError, match="unknown kind"):
        await list_cached_items(None, kind="not-a-real-kind")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_get_cached_item_unknown_kind_raises() -> None:
    with pytest.raises(ValueError, match="unknown kind"):
        await get_cached_item(
            None,  # type: ignore[arg-type]
            source_handle="anything",
            kind="not-a-real-kind",
            slug="x",
        )
