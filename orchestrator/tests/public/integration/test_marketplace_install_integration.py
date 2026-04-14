"""Integration tests for /api/v1/marketplace/install endpoints."""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5433/test")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DEPLOYMENT_MODE", "docker")
os.environ.setdefault("LITELLM_API_BASE", "http://localhost:4000/v1")
os.environ.setdefault("LITELLM_MASTER_KEY", "test-key")

pytestmark = pytest.mark.asyncio


def _user(scopes=None):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.default_team_id = None
    u.is_active = True
    key = MagicMock()
    key.id = uuid.uuid4()
    key.key_prefix = "tsk_test"
    key.scopes = scopes
    u._api_key_record = key
    return u


def _scalar(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalars(items):
    r = MagicMock()
    r.scalars.return_value.all.return_value = items
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


def _agent(**overrides):
    a = MagicMock()
    a.id = overrides.get("id", uuid.uuid4())
    a.slug = overrides.get("slug", "coder")
    a.item_type = overrides.get("item_type", "agent")
    a.pricing_type = overrides.get("pricing_type", "free")
    a.is_active = True
    return a


class TestInstall:
    async def test_install_free_agent_creates_receipt(self, client_factory, mock_db):
        from app.permissions import Permission

        user = _user(scopes=[Permission.MARKETPLACE_INSTALL.value])
        agent = _agent()
        # execute calls: resolve_item (agent), _existing_purchase (None)
        mock_db.execute = AsyncMock(side_effect=[_scalar(agent), _scalar(None)])

        client = await client_factory(user)
        async with client as ac:
            resp = await ac.post(
                "/api/v1/marketplace/install",
                json={"item_type": "agent", "slug": "coder"},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["newly_installed"] is True
        assert body["purchase_type"] == "free"
        assert body["download"]["manifest_url"].endswith("/coder/manifest")

    async def test_install_paid_without_purchase_returns_402(self, client_factory, mock_db):
        from app.permissions import Permission

        user = _user(scopes=[Permission.MARKETPLACE_INSTALL.value])
        agent = _agent(pricing_type="paid")
        mock_db.execute = AsyncMock(side_effect=[_scalar(agent), _scalar(None)])

        client = await client_factory(user)
        async with client as ac:
            resp = await ac.post(
                "/api/v1/marketplace/install",
                json={"item_type": "agent", "slug": "pro"},
            )
        assert resp.status_code == 402

    async def test_install_missing_scope_403(self, client_factory, mock_db):
        from app.permissions import Permission

        user = _user(scopes=[Permission.MARKETPLACE_READ.value])
        client = await client_factory(user)
        async with client as ac:
            resp = await ac.post(
                "/api/v1/marketplace/install",
                json={"item_type": "agent", "slug": "coder"},
            )
        assert resp.status_code == 403


class TestListInstalled:
    async def test_list_installed_returns_agents_and_bases(self, client_factory, mock_db):
        from app.permissions import Permission

        user = _user(scopes=[Permission.MARKETPLACE_INSTALL.value])

        agent_row = MagicMock()
        agent_row.id = uuid.uuid4()
        agent_row.agent_id = uuid.uuid4()
        agent_row.agent.item_type = "agent"
        agent_row.purchase_type = "free"
        agent_row.purchase_date = datetime(2026, 4, 12)
        agent_row.expires_at = None
        agent_row.is_active = True
        if hasattr(agent_row, "base_id"):
            del agent_row.base_id

        base_row = MagicMock(spec=[])
        base_row.id = uuid.uuid4()
        base_row.base_id = uuid.uuid4()
        base_row.purchase_type = "free"
        base_row.purchase_date = datetime(2026, 4, 13)
        base_row.is_active = True

        mock_db.execute = AsyncMock(side_effect=[_scalars([agent_row]), _scalars([base_row])])

        client = await client_factory(user)
        async with client as ac:
            resp = await ac.get("/api/v1/marketplace/installed")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 2
        # Base was more recent, sorts first
        assert body["items"][0]["item_type"] == "base"


class TestAckInstall:
    async def test_ack_agent_receipt_ok(self, client_factory, mock_db):
        from app.permissions import Permission

        user = _user(scopes=[Permission.MARKETPLACE_INSTALL.value])
        receipt_id = uuid.uuid4()

        agent_row = MagicMock(id=receipt_id)
        mock_db.execute = AsyncMock(return_value=_scalar(agent_row))

        client = await client_factory(user)
        async with client as ac:
            resp = await ac.post(
                f"/api/v1/marketplace/install/{receipt_id}/ack",
                json={"installed_path": "/Users/me/.tesslate/agents/coder"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["acknowledged"] is True
        assert body["resource_type"] == "agent"

    async def test_ack_unknown_receipt_404(self, client_factory, mock_db):
        from app.permissions import Permission

        user = _user(scopes=[Permission.MARKETPLACE_INSTALL.value])
        receipt_id = uuid.uuid4()
        # Both agent and base lookups return None
        mock_db.execute = AsyncMock(side_effect=[_scalar(None), _scalar(None)])

        client = await client_factory(user)
        async with client as ac:
            resp = await ac.post(
                f"/api/v1/marketplace/install/{receipt_id}/ack",
                json={},
            )
        assert resp.status_code == 404
