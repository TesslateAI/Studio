"""Unit tests for Wave 3 Tesslate Apps routers.

Uses FastAPI dependency overrides + mocked service layer. No real DB or
hub calls; we stub `publisher.publish_version`, `installer.install_app`,
and `get_db` / `current_active_user`.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.routers import app_installs, app_versions, marketplace_apps
from app.services.apps.installer import (
    AlreadyInstalledError,
    IncompatibleAppError,
    InstallResult,
)
from app.services.apps.publisher import (
    CompatibilityError,
    DuplicateVersionError,
    PublishResult,
)
from app.services.apps import compatibility as compat_mod
from app.users import current_active_user


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fake_user(is_superuser: bool = False) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), is_superuser=is_superuser)


def _mk_app(publish_fn=None, install_fn=None, db_rows=None) -> FastAPI:
    app = FastAPI()
    app.include_router(app_versions.router, prefix="/api/app-versions")
    app.include_router(app_installs.router, prefix="/api/app-installs")
    app.include_router(marketplace_apps.router, prefix="/api/marketplace-apps")

    fake_user = _fake_user()

    async def _db_override():
        # The router methods that we test either never touch db (mocks swap
        # out service calls) or we want to stub execute for list_my_installs.
        session = MagicMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.flush = AsyncMock()
        if db_rows is not None:
            exec_result = MagicMock()
            exec_result.scalar_one = MagicMock(return_value=len(db_rows))
            exec_result.all = MagicMock(return_value=db_rows)
            session.execute = AsyncMock(return_value=exec_result)
        yield session

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[current_active_user] = lambda: fake_user

    # Hub client stub — instantiated via Depends; override to a MagicMock.
    async def _hub_client():
        hc = MagicMock()
        hc.close = AsyncMock()
        return hc

    app.dependency_overrides[app_versions._get_hub_client] = _hub_client
    app.dependency_overrides[app_installs._get_hub_client] = _hub_client

    if publish_fn is not None:
        app.state._publish_fn = publish_fn
    if install_fn is not None:
        app.state._install_fn = install_fn
    app.state._fake_user = fake_user
    return app


@pytest.fixture
def publish_client(monkeypatch):
    async def _make(publish_fn):
        monkeypatch.setattr(
            "app.routers.app_versions.publish_version", publish_fn
        )
        app = _mk_app()
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test"), app

    return _make


@pytest.fixture
def install_client(monkeypatch):
    async def _make(install_fn):
        monkeypatch.setattr(
            "app.routers.app_installs.install_app", install_fn
        )
        app = _mk_app()
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test"), app

    return _make


# ---------------------------------------------------------------------------
# Publish tests
# ---------------------------------------------------------------------------


async def test_publish_endpoint_returns_201_on_happy_path(publish_client):
    app_id = uuid4()
    version_id = uuid4()
    sub_id = uuid4()

    async def fake_publish(*args, **kwargs):
        return PublishResult(
            app_id=app_id,
            app_version_id=version_id,
            version="1.0.0",
            bundle_hash="sha256:abc",
            manifest_hash="sha256:def",
            submission_id=sub_id,
        )

    client, _ = await publish_client(fake_publish)
    async with client as c:
        r = await c.post(
            "/api/app-versions/publish",
            json={
                "project_id": str(uuid4()),
                "manifest": {"app": {"slug": "x", "version": "1.0.0"}},
            },
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["app_id"] == str(app_id)
    assert body["version"] == "1.0.0"


async def test_publish_endpoint_409_on_duplicate(publish_client):
    async def fake_publish(*args, **kwargs):
        raise DuplicateVersionError("already exists")

    client, _ = await publish_client(fake_publish)
    async with client as c:
        r = await c.post(
            "/api/app-versions/publish",
            json={"project_id": str(uuid4()), "manifest": {}},
        )
    assert r.status_code == 409
    assert "already exists" in r.json()["detail"]


async def test_publish_endpoint_422_on_compat_fail(publish_client):
    async def fake_publish(*args, **kwargs):
        report = compat_mod.CompatReport(
            compatible=False,
            missing_features=["xyz"],
            unsupported_manifest_schema=False,
            upgrade_required=False,
            server_manifest_schemas=["2025-01"],
            server_feature_set_hash="hash",
        )
        raise CompatibilityError("nope", report)

    client, _ = await publish_client(fake_publish)
    async with client as c:
        r = await c.post(
            "/api/app-versions/publish",
            json={"project_id": str(uuid4()), "manifest": {}},
        )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Install tests
# ---------------------------------------------------------------------------


async def test_install_endpoint_returns_201(install_client):
    inst_id = uuid4()
    proj_id = uuid4()

    async def fake_install(*args, **kwargs):
        return InstallResult(
            app_instance_id=inst_id,
            project_id=proj_id,
            volume_id="vol-1",
            node_name="node-a",
        )

    client, _ = await install_client(fake_install)
    async with client as c:
        r = await c.post(
            "/api/app-installs/install",
            json={
                "app_version_id": str(uuid4()),
                "team_id": str(uuid4()),
                "wallet_mix_consent": {},
                "mcp_consents": [],
            },
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["app_instance_id"] == str(inst_id)
    assert body["volume_id"] == "vol-1"


async def test_install_endpoint_409_on_already_installed(install_client):
    async def fake_install(*args, **kwargs):
        raise AlreadyInstalledError("dup")

    client, _ = await install_client(fake_install)
    async with client as c:
        r = await c.post(
            "/api/app-installs/install",
            json={
                "app_version_id": str(uuid4()),
                "team_id": str(uuid4()),
                "wallet_mix_consent": {},
                "mcp_consents": [],
            },
        )
    assert r.status_code == 409


async def test_install_endpoint_422_on_incompat(install_client):
    async def fake_install(*args, **kwargs):
        raise IncompatibleAppError("missing features")

    client, _ = await install_client(fake_install)
    async with client as c:
        r = await c.post(
            "/api/app-installs/install",
            json={
                "app_version_id": str(uuid4()),
                "team_id": str(uuid4()),
                "wallet_mix_consent": {},
                "mcp_consents": [],
            },
        )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# List installs
# ---------------------------------------------------------------------------


async def test_list_my_installs():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)

    def _fake_instance(**kw):
        base = dict(
            id=uuid4(),
            app_id=uuid4(),
            app_version_id=uuid4(),
            project_id=uuid4(),
            state="installed",
            update_policy="manual",
            volume_id="vol-x",
            installed_at=now,
            uninstalled_at=None,
            created_at=now,
        )
        base.update(kw)
        return SimpleNamespace(**base)

    rows = [
        (_fake_instance(), "slug-a", "App A", "1.0.0"),
        (_fake_instance(), "slug-b", "App B", "2.0.0"),
    ]

    app = FastAPI()
    app.include_router(app_installs.router, prefix="/api/app-installs")

    fake_user = _fake_user()

    class _ExecResult:
        def __init__(self, rows):
            self._rows = rows

        def scalar_one(self):
            return len(self._rows)

        def all(self):
            return self._rows

    class _Session:
        def __init__(self, rows):
            self._rows = rows
            self._call = 0

        async def execute(self, stmt):
            self._call += 1
            # First call: count. Second call: rows.
            if self._call == 1:
                return _ExecResult(self._rows)
            return _ExecResult(self._rows)

    async def _db_override():
        yield _Session(rows)

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[current_active_user] = lambda: fake_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/app-installs/mine")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert body["items"][0]["app_slug"] == "slug-a"
    assert body["items"][1]["app_version"] == "2.0.0"
