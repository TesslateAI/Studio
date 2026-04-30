"""
Unit tests for ``app.services.marketplace_federation``.

Covers:
  - install_guard for every (trust_level, kind) cell of the matrix.
  - dispatch_purchase for the four routing rules.
  - mcp_install_prompt parsing tolerance + destructive-tool extraction.

Pure-Python; no DB. The federation facade's cache helpers
(``list_cached_items`` / ``get_cached_item``) are exercised in the sync
integration tests where a real DB is needed.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.marketplace_federation import (
    InstallGuardResult,
    PurchaseRoute,
    dispatch_purchase,
    install_guard,
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
