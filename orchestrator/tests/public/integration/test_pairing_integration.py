"""Integration tests for desktop pairing endpoints."""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5433/test")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DEPLOYMENT_MODE", "docker")
os.environ.setdefault("LITELLM_API_BASE", "http://localhost:4000/v1")
os.environ.setdefault("LITELLM_MASTER_KEY", "test-key")

pytestmark = pytest.mark.asyncio


def _session_user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.is_active = True
    u.default_team_id = None
    return u


def _tsk_user(scopes=None, api_key_id=None):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.is_active = True
    u.default_team_id = None
    key = MagicMock()
    key.id = api_key_id or uuid.uuid4()
    key.key_prefix = "tsk_test"
    key.scopes = scopes  # None = all allowed
    u._api_key_record = key
    return u


@pytest.fixture
def mock_db():
    db = AsyncMock()

    async def _commit():
        return None

    async def _flush():
        return None

    async def _refresh(obj):
        # Simulate DB defaults
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        return None

    db.commit.side_effect = _commit
    db.flush.side_effect = _flush
    db.refresh.side_effect = _refresh
    db.add = MagicMock()
    return db


@pytest.fixture
async def session_client(mock_db):
    from app.database import get_db
    from app.main import app
    from app.users import current_active_user

    user = _session_user()

    async def _override_db():
        yield mock_db

    # Bearer header short-circuits CSRF middleware; use a non-tsk placeholder
    # since the real auth is replaced by the dependency override below.
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[current_active_user] = lambda: user

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer session-test"},
    ) as ac:
        yield ac, user

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/desktop/pair/complete
# ---------------------------------------------------------------------------


class TestPairComplete:
    async def test_mint_returns_token_and_device(self, session_client, mock_db):
        client, user = session_client

        # Active devices query returns empty list
        empty = MagicMock()
        empty.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=empty)

        resp = await client.post(
            "/api/desktop/pair/complete",
            json={
                "device_name": "My Mac",
                "device_platform": "darwin",
                "app_version": "0.1.0",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["token"].startswith("tsk_")
        assert "device_id" in body
        assert "api_key_id" in body
        assert "desktop.pair" in body["scopes"]

    async def test_mint_rejects_when_at_device_cap(self, session_client, mock_db):
        client, user = session_client

        # 10 active devices already
        devs = [MagicMock(revoked_at=None) for _ in range(10)]
        full = MagicMock()
        full.scalars.return_value.all.return_value = devs
        mock_db.execute = AsyncMock(return_value=full)

        resp = await client.post(
            "/api/desktop/pair/complete",
            json={"device_name": "Extra"},
        )
        assert resp.status_code == 400
        assert "Maximum" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/v1/desktop/pair/revoke
# ---------------------------------------------------------------------------


class TestPairRevoke:
    async def test_revoke_flips_key_and_device(self, mock_db):
        from app.auth_external import get_external_api_user
        from app.database import get_db
        from app.main import app
        from app.permissions import Permission

        user = _tsk_user(scopes=[Permission.DESKTOP_PAIR.value])

        async def _override_db():
            yield mock_db

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_external_api_user] = lambda: user

        device = MagicMock()
        device.id = uuid.uuid4()
        device.revoked_at = None

        key_row = MagicMock()
        key_row.id = user._api_key_record.id
        key_row.is_active = True

        dev_result = MagicMock()
        dev_result.scalar_one_or_none.return_value = device
        key_result = MagicMock()
        key_result.scalar_one_or_none.return_value = key_row
        mock_db.execute = AsyncMock(side_effect=[dev_result, key_result])

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/api/v1/desktop/pair/revoke",
                headers={"Authorization": "Bearer tsk_test"},
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["revoked"] is True
        assert body["device_id"] == str(device.id)
        assert device.revoked_at is not None
        assert key_row.is_active is False

    async def test_revoke_without_scope_returns_403(self, mock_db):
        from app.auth_external import get_external_api_user
        from app.database import get_db
        from app.main import app
        from app.permissions import Permission

        # Key explicitly scoped without DESKTOP_PAIR → 403
        user = _tsk_user(scopes=[Permission.MODELS_PROXY.value])

        async def _override_db():
            yield mock_db

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_external_api_user] = lambda: user

        # The scope dep issues a secondary DB lookup for the membership check; the
        # user has no default_team_id, so that branch is skipped.

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/api/v1/desktop/pair/revoke",
                headers={"Authorization": "Bearer tsk_test"},
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 403
        assert Permission.DESKTOP_PAIR.value in resp.json()["detail"]
