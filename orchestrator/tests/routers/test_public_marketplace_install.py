"""
Wave 4 — install_guard enforcement on the public install endpoint.

The desktop / SDK install path lives at ``POST /api/v1/marketplace/install``
(``app.routers.public.marketplace_install``). It MUST run the federation
trust gate before recording a purchase row, mirroring the authenticated
browser-side install paths in ``app.routers.marketplace`` /
``app.routers.mcp``.

These tests pin the contract against trust-failure outcomes:

* ``trust_level='untrusted'`` → 403 ``install_blocked`` for ``mcp_server``.
* ``trust_level='untrusted'`` → 403 ``install_blocked`` for ``app`` (when
  the public install endpoint exposes that kind in the future — guarded
  by the same code path).
* ``trust_level='private'`` mcp_server install without ``confirmed=True``
  → 409 ``install_requires_confirmation`` carrying ``scope_tool_list``,
  ``destructive_tools``, and a ``prompt`` block (transport / command /
  args / env_keys / scope_list) the desktop UI renders into the
  permission modal.
* ``trust_level='private'`` mcp_server install with ``confirmed=True`` →
  proceeds past the guard.
* ``trust_level='local'`` ``scope='team'`` rows require the requester
  to be an active member of the owning team — non-members get 403.

Tests mock the DB at the dependency-injection layer (no live Postgres
required) and use ``ASGITransport`` to drive the FastAPI app in-process.
"""
from __future__ import annotations

import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5433/test")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DEPLOYMENT_MODE", "docker")
os.environ.setdefault("LITELLM_API_BASE", "http://localhost:4000/v1")
os.environ.setdefault("LITELLM_MASTER_KEY", "test-key")

pytestmark = pytest.mark.asyncio


_MCP_TOOL_CONFIG: dict[str, Any] = {
    "transport": "stdio",
    "command": "node",
    "args": ["server.js"],
    "env": {"API_TOKEN": "secret"},
    "tools": [
        {"name": "ls", "description": "list files", "destructive": False},
        {"name": "rm", "description": "delete file", "destructive": True},
    ],
    "scopes": ["fs.read", "fs.write"],
}


def _user(scopes: list[str] | None = None, default_team_id: uuid.UUID | None = None) -> MagicMock:
    """Authenticated tsk_-key user. Default team is unset to bypass audit writes
    (``audit_write`` is a no-op when ``default_team_id is None``)."""
    u = MagicMock()
    u.id = uuid.uuid4()
    u.default_team_id = default_team_id
    u.is_active = True
    key = MagicMock()
    key.id = uuid.uuid4()
    key.key_prefix = "tsk_test"
    key.scopes = scopes
    u._api_key_record = key
    return u


def _agent_mcp(
    *,
    source_id: uuid.UUID | None = None,
    pricing_type: str = "free",
    config: dict[str, Any] | None = None,
) -> MagicMock:
    a = MagicMock()
    a.id = uuid.uuid4()
    a.slug = "wave4-mcp"
    a.item_type = "mcp_server"
    a.pricing_type = pricing_type
    a.is_active = True
    a.source_id = source_id
    a.config = config if config is not None else _MCP_TOOL_CONFIG
    return a


def _agent_simple(
    *,
    source_id: uuid.UUID | None = None,
    pricing_type: str = "free",
) -> MagicMock:
    a = MagicMock()
    a.id = uuid.uuid4()
    a.slug = "coder"
    a.item_type = "agent"
    a.pricing_type = pricing_type
    a.is_active = True
    a.source_id = source_id
    return a


def _source(
    *,
    trust_level: str,
    scope: str = "system",
    is_active: bool = True,
    handle: str | None = None,
    user_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
) -> MagicMock:
    s = MagicMock()
    s.id = uuid.uuid4()
    s.handle = handle or f"{trust_level}-test-hub"
    s.trust_level = trust_level
    s.scope = scope
    s.is_active = is_active
    s.user_id = user_id
    s.team_id = team_id
    return s


def _scalar(value: Any) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()

    async def _refresh(row):
        if getattr(row, "id", None) is None:
            row.id = uuid.uuid4()
        if not hasattr(row, "purchase_type"):
            row.purchase_type = "free"

    db.refresh = AsyncMock(side_effect=_refresh)
    return db


@pytest.fixture
async def client_factory(mock_db):
    from app.auth_external import get_external_api_user
    from app.database import get_db
    from app.main import app

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db

    async def _make(user):
        app.dependency_overrides[get_external_api_user] = lambda: user
        return AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer tsk_test"},
        )

    yield _make
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Untrusted source → mcp_server install blocked outright
# ---------------------------------------------------------------------------


class TestUntrustedInstallBlocked:
    async def test_install_mcp_from_untrusted_source_returns_403(
        self, client_factory, mock_db
    ):
        from app.permissions import Permission

        user = _user(scopes=[Permission.MARKETPLACE_INSTALL.value])
        source = _source(trust_level="untrusted")
        agent = _agent_mcp(source_id=source.id)

        # execute order: resolve_item -> _load_install_source
        mock_db.execute = AsyncMock(side_effect=[_scalar(agent), _scalar(source)])

        client = await client_factory(user)
        async with client as ac:
            resp = await ac.post(
                "/api/v1/marketplace/install",
                json={"item_type": "mcp_server", "slug": "wave4-mcp"},
            )

        assert resp.status_code == 403, resp.text
        detail = resp.json().get("detail")
        assert isinstance(detail, dict)
        assert detail.get("error") == "install_blocked"
        assert detail.get("kind") == "mcp_server"
        assert detail.get("source_handle") == source.handle
        assert "untrusted" in detail.get("reason", "")
        # State must NOT have been mutated.
        mock_db.add.assert_not_called()


# ---------------------------------------------------------------------------
# Private source → mcp_server install requires confirmation; the 409 body
# carries the structured prompt the desktop UI renders.
# ---------------------------------------------------------------------------


class TestPrivateRequiresConfirmation:
    async def test_install_mcp_private_without_confirmed_returns_409(
        self, client_factory, mock_db
    ):
        from app.permissions import Permission

        user = _user(scopes=[Permission.MARKETPLACE_INSTALL.value])
        source = _source(trust_level="private")
        agent = _agent_mcp(source_id=source.id)
        mock_db.execute = AsyncMock(side_effect=[_scalar(agent), _scalar(source)])

        client = await client_factory(user)
        async with client as ac:
            resp = await ac.post(
                "/api/v1/marketplace/install",
                json={
                    "item_type": "mcp_server",
                    "slug": "wave4-mcp",
                    "confirmed": False,
                },
            )

        assert resp.status_code == 409, resp.text
        detail = resp.json().get("detail")
        assert isinstance(detail, dict)
        assert detail.get("error") == "install_requires_confirmation"
        assert detail.get("kind") == "mcp_server"
        # Trust-matrix surface
        destructive = detail.get("destructive_tools") or []
        assert "rm" in destructive
        scope_tool_list = detail.get("scope_tool_list") or []
        tool_names = {t.get("name") for t in scope_tool_list if isinstance(t, dict)}
        assert {"ls", "rm"}.issubset(tool_names)
        # mcp_server-specific UI prompt
        prompt = detail.get("prompt") or {}
        assert prompt.get("transport") == "stdio"
        assert prompt.get("command") == "node"
        assert prompt.get("args") == ["server.js"]
        assert "API_TOKEN" in (prompt.get("env_keys") or [])
        assert "fs.read" in (prompt.get("scope_list") or [])
        # No row written.
        mock_db.add.assert_not_called()

    async def test_install_mcp_private_with_confirmed_succeeds(
        self, client_factory, mock_db
    ):
        from app.permissions import Permission

        user = _user(scopes=[Permission.MARKETPLACE_INSTALL.value])
        source = _source(trust_level="private")
        agent = _agent_mcp(source_id=source.id)

        # execute order: resolve_item -> _load_install_source -> _existing_purchase
        mock_db.execute = AsyncMock(
            side_effect=[_scalar(agent), _scalar(source), _scalar(None)]
        )

        client = await client_factory(user)
        async with client as ac:
            resp = await ac.post(
                "/api/v1/marketplace/install",
                json={
                    "item_type": "mcp_server",
                    "slug": "wave4-mcp",
                    "confirmed": True,
                },
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["newly_installed"] is True
        assert body["item_type"] == "mcp_server"
        # The install proceeded → record_install added a UserPurchasedAgent row.
        mock_db.add.assert_called_once()


# ---------------------------------------------------------------------------
# Local team-scoped source → owner-membership check enforced at the router.
# ---------------------------------------------------------------------------


class TestLocalTeamOwnerCheck:
    async def test_team_scoped_local_source_blocks_non_member(
        self, client_factory, mock_db, monkeypatch
    ):
        from app.permissions import Permission

        team_id = uuid.uuid4()
        user = _user(scopes=[Permission.MARKETPLACE_INSTALL.value])
        source = _source(trust_level="local", scope="team", team_id=team_id)
        agent = _agent_simple(source_id=source.id)

        # execute order: resolve_item -> _load_install_source.
        # The team-membership check is patched below.
        mock_db.execute = AsyncMock(side_effect=[_scalar(agent), _scalar(source)])

        async def _no_membership(db, team_id_arg, user_id_arg):
            return None

        # Patch the helper at the router import site.
        monkeypatch.setattr(
            "app.routers.public.marketplace_install.get_team_membership",
            _no_membership,
        )

        client = await client_factory(user)
        async with client as ac:
            resp = await ac.post(
                "/api/v1/marketplace/install",
                json={"item_type": "agent", "slug": "coder"},
            )

        assert resp.status_code == 403, resp.text
        detail = resp.json().get("detail")
        assert isinstance(detail, dict)
        assert detail.get("error") == "install_blocked"
        assert detail.get("reason") == "local_team_owner_check_required"
        assert detail.get("kind") == "agent"
        mock_db.add.assert_not_called()

    async def test_team_scoped_local_source_allows_active_member(
        self, client_factory, mock_db, monkeypatch
    ):
        from app.permissions import Permission

        team_id = uuid.uuid4()
        user = _user(scopes=[Permission.MARKETPLACE_INSTALL.value])
        source = _source(trust_level="local", scope="team", team_id=team_id)
        agent = _agent_simple(source_id=source.id)

        # execute order: resolve_item -> _load_install_source -> _existing_purchase
        mock_db.execute = AsyncMock(
            side_effect=[_scalar(agent), _scalar(source), _scalar(None)]
        )

        async def _active_membership(db, team_id_arg, user_id_arg):
            membership = MagicMock()
            membership.team_id = team_id_arg
            membership.user_id = user_id_arg
            membership.is_active = True
            membership.role = "editor"
            return membership

        monkeypatch.setattr(
            "app.routers.public.marketplace_install.get_team_membership",
            _active_membership,
        )

        client = await client_factory(user)
        async with client as ac:
            resp = await ac.post(
                "/api/v1/marketplace/install",
                json={"item_type": "agent", "slug": "coder"},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["newly_installed"] is True
        mock_db.add.assert_called_once()
