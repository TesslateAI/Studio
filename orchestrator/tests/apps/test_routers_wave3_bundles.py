"""Wave 3 router tests: AppBundle CRUD + install.

These are lightweight unit tests that mount the router on a bare FastAPI
app and override the auth + DB dependencies. The bundles service and
installer are patched via monkeypatch so the tests don't touch Postgres.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.routers.app_bundles import router as bundles_router
from app.services.apps import bundles as bundles_svc
from app.services.apps import installer as installer_svc
from app.users import current_active_user, current_superuser


def _user(is_super: bool = False) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), is_superuser=is_super, is_active=True)


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    # Default: list query returns zero rows.
    exec_result = MagicMock()
    exec_result.scalar_one.return_value = 0
    exec_result.scalar_one_or_none.return_value = None
    scalars = MagicMock()
    scalars.all.return_value = []
    exec_result.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=exec_result)
    return db


def _build_app(user: SimpleNamespace, db: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(bundles_router, prefix="/api/app-bundles")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_active_user] = lambda: user
    app.dependency_overrides[current_superuser] = lambda: (
        user if user.is_superuser else (_ for _ in ()).throw(
            __import__("fastapi").HTTPException(status_code=403, detail="not admin")
        )
    )
    return app


@pytest.fixture
async def client_factory(mock_db):
    async def factory(user: SimpleNamespace):
        app = _build_app(user, mock_db)
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")
    return factory


async def test_create_bundle_happy_path(monkeypatch, client_factory):
    new_id = uuid.uuid4()

    async def fake_create_bundle(db, **kw):
        assert kw["slug"] == "my-bundle"
        assert len(kw["items"]) == 1
        return new_id

    monkeypatch.setattr(bundles_svc, "create_bundle", fake_create_bundle)
    async with await client_factory(_user()) as c:
        r = await c.post(
            "/api/app-bundles",
            json={
                "slug": "my-bundle", "display_name": "B",
                "items": [{"app_version_id": str(uuid.uuid4())}],
            },
        )
    assert r.status_code == 201
    assert r.json()["bundle_id"] == str(new_id)


async def test_create_bundle_slug_conflict_409(monkeypatch, client_factory):
    async def fake_create_bundle(db, **kw):
        raise bundles_svc.BundleSlugTakenError(kw["slug"])

    monkeypatch.setattr(bundles_svc, "create_bundle", fake_create_bundle)
    async with await client_factory(_user()) as c:
        r = await c.post(
            "/api/app-bundles",
            json={
                "slug": "dup", "display_name": "B",
                "items": [{"app_version_id": str(uuid.uuid4())}],
            },
        )
    assert r.status_code == 409


async def test_get_bundle_404(mock_db, client_factory):
    # mock_db.execute returns scalar_one_or_none=None by default.
    async with await client_factory(_user()) as c:
        r = await c.get(f"/api/app-bundles/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_publish_bundle_requires_admin(monkeypatch, client_factory):
    async def fake_publish(db, **kw):
        return None

    monkeypatch.setattr(bundles_svc, "publish_bundle", fake_publish)
    bid = uuid.uuid4()

    # Non-admin → 403.
    async with await client_factory(_user(is_super=False)) as c:
        r = await c.post(f"/api/app-bundles/{bid}/publish")
    assert r.status_code == 403

    # Admin → 204.
    async with await client_factory(_user(is_super=True)) as c:
        r = await c.post(f"/api/app-bundles/{bid}/publish")
    assert r.status_code == 204


async def test_yank_bundle_requires_admin(monkeypatch, client_factory):
    async def fake_yank(db, **kw):
        return None

    monkeypatch.setattr(bundles_svc, "yank_bundle", fake_yank)
    bid = uuid.uuid4()

    async with await client_factory(_user(is_super=False)) as c:
        r = await c.post(f"/api/app-bundles/{bid}/yank", json={"reason": "bug"})
    assert r.status_code == 403

    async with await client_factory(_user(is_super=True)) as c:
        r = await c.post(f"/api/app-bundles/{bid}/yank", json={"reason": "bug"})
    assert r.status_code == 204


async def test_install_bundle_partial_success_207(monkeypatch, client_factory):
    av1 = uuid.uuid4()
    av2 = uuid.uuid4()
    bid = uuid.uuid4()

    async def fake_get_bundle(db, *, bundle_id):
        return {
            "id": bid, "slug": "b", "display_name": "B", "status": "approved",
            "consolidated_manifest_hash": None,
            "items": [
                {"app_version_id": av1, "order_index": 0, "default_enabled": True, "required": True},
                {"app_version_id": av2, "order_index": 1, "default_enabled": True, "required": False},
            ],
        }

    monkeypatch.setattr(bundles_svc, "get_bundle", fake_get_bundle)

    @dataclass
    class _Res:
        app_instance_id: uuid.UUID
        project_id: uuid.UUID
        volume_id: str = "v"
        node_name: str = "n"

    async def fake_install(db, **kw):
        if kw["app_version_id"] == av1:
            return _Res(app_instance_id=uuid.uuid4(), project_id=uuid.uuid4())
        raise installer_svc.IncompatibleAppError("boom")

    monkeypatch.setattr(installer_svc, "install_app", fake_install)

    async with await client_factory(_user()) as c:
        r = await c.post(
            f"/api/app-bundles/{bid}/install",
            json={
                "team_id": str(uuid.uuid4()),
                "installs": [
                    {"app_version_id": str(av1), "wallet_mix_consent": {}, "mcp_consents": []},
                    {"app_version_id": str(av2), "wallet_mix_consent": {}, "mcp_consents": []},
                ],
            },
        )
    assert r.status_code == 207
    body = r.json()
    assert len(body["succeeded"]) == 1
    assert body["succeeded"][0]["app_version_id"] == str(av1)
    assert len(body["failed"]) == 1
    assert body["failed"][0]["app_version_id"] == str(av2)
    assert "rolled back" in (body["note"] or "")


async def test_list_bundles_filters_by_status(mock_db, client_factory):
    # Capture the SQL statement passed to db.execute. We assert a WHERE
    # clause references status='approved'.
    captured: list[Any] = []

    async def recording_execute(stmt):
        captured.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
        result = MagicMock()
        result.scalar_one.return_value = 0
        scalars = MagicMock()
        scalars.all.return_value = []
        result.scalars.return_value = scalars
        return result

    mock_db.execute = recording_execute

    async with await client_factory(_user(is_super=True)) as c:
        r = await c.get("/api/app-bundles?status=approved")
    assert r.status_code == 200
    joined = "\n".join(captured).lower()
    assert "'approved'" in joined or "approved" in joined

    # Invalid status → 400.
    async with await client_factory(_user(is_super=True)) as c:
        r = await c.get("/api/app-bundles?status=bogus")
    assert r.status_code == 400
