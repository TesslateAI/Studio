"""Integration tests for /api/v1/projects/sync/* endpoints."""
from __future__ import annotations

import io
import json
import os
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5433/test")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DEPLOYMENT_MODE", "docker")
os.environ.setdefault("LITELLM_API_BASE", "http://localhost:4000/v1")
os.environ.setdefault("LITELLM_MASTER_KEY", "test-key")

pytestmark = pytest.mark.asyncio


class InMemoryStorage:
    def __init__(self):
        self.blobs = {}

    async def put(self, key, data):
        self.blobs[key] = data

    async def get(self, key):
        if key not in self.blobs:
            raise FileNotFoundError(key)
        return self.blobs[key]

    async def exists(self, key):
        return key in self.blobs


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
    r.scalar_one.return_value = value
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

    db.refresh = AsyncMock(side_effect=_refresh)
    return db


@pytest.fixture
def storage():
    from app.services.public.sync_service import set_sync_storage

    s = InMemoryStorage()
    set_sync_storage(s)
    yield s
    set_sync_storage(None)


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


def _mock_project_access(project_id):
    project = MagicMock()
    project.id = project_id
    project.slug = "proj"
    project.owner_id = uuid.uuid4()
    project.team_id = None
    project.visibility = "private"

    async def _access(db, slug, user_id, permission):
        return project, "admin"

    return project, _access


# ---------------------------------------------------------------------------


class TestPush:
    async def test_push_first_sync_creates_snapshot(self, client_factory, mock_db, storage):
        from app.permissions import Permission

        user = _user(scopes=[Permission.PROJECTS_SYNC.value, Permission.PROJECT_EDIT.value])
        project_id = uuid.uuid4()
        project, access = _mock_project_access(project_id)

        # No existing sync snapshot
        mock_db.execute = AsyncMock(return_value=_scalar(None))

        manifest = {"README.md": "abc123", "src/main.py": "def456"}
        zip_bytes = b"PK\x03\x04fake-zip-contents"

        with patch("app.routers.public.projects_sync.get_project_with_access", new=access):
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.post(
                    "/api/v1/projects/sync/push",
                    data={
                        "project_id": str(project_id),
                        "manifest": json.dumps(manifest),
                        "label": "first push",
                    },
                    files={"zip_file": ("proj.zip", io.BytesIO(zip_bytes), "application/zip")},
                )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["created"] is True
        assert body["size_bytes"] == len(zip_bytes)
        assert body["conflicts"] == []
        # Blob landed in storage
        assert body["blob_key"] in storage.blobs

    async def test_push_detects_conflicts_returns_409(self, client_factory, mock_db, storage):
        from app.permissions import Permission

        user = _user(scopes=[Permission.PROJECTS_SYNC.value, Permission.PROJECT_EDIT.value])
        project_id = uuid.uuid4()
        project, access = _mock_project_access(project_id)

        cloud_snapshot = MagicMock()
        cloud_snapshot.id = uuid.uuid4()
        cloud_snapshot.sync_manifest = {"README.md": "OLD", "unchanged.py": "same"}

        mock_db.execute = AsyncMock(return_value=_scalar(cloud_snapshot))

        incoming = {"README.md": "NEW", "unchanged.py": "same"}
        with patch("app.routers.public.projects_sync.get_project_with_access", new=access):
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.post(
                    "/api/v1/projects/sync/push",
                    data={
                        "project_id": str(project_id),
                        "manifest": json.dumps(incoming),
                    },
                    files={"zip_file": ("p.zip", io.BytesIO(b"zip"), "application/zip")},
                )

        assert resp.status_code == 409, resp.text
        detail = resp.json()["detail"]
        assert detail["latest_snapshot_id"] == str(cloud_snapshot.id)
        assert len(detail["conflicts"]) == 1
        assert detail["conflicts"][0]["path"] == "README.md"

    async def test_push_too_large_returns_413(self, client_factory, mock_db, storage, monkeypatch):
        from app.permissions import Permission

        user = _user(scopes=[Permission.PROJECTS_SYNC.value, Permission.PROJECT_EDIT.value])
        project_id = uuid.uuid4()
        project, access = _mock_project_access(project_id)

        mock_db.execute = AsyncMock(return_value=_scalar(None))

        # Lower the cap for the test
        monkeypatch.setattr("app.routers.public.projects_sync.MAX_PUSH_BYTES", 10)

        with patch("app.routers.public.projects_sync.get_project_with_access", new=access):
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.post(
                    "/api/v1/projects/sync/push",
                    data={"project_id": str(project_id), "manifest": "{}"},
                    files={"zip_file": ("p.zip", io.BytesIO(b"x" * 100), "application/zip")},
                )

        assert resp.status_code == 413

    async def test_push_missing_scope_403(self, client_factory, mock_db, storage):
        from app.permissions import Permission

        user = _user(scopes=[Permission.MARKETPLACE_READ.value])
        client = await client_factory(user)
        async with client as ac:
            resp = await ac.post(
                "/api/v1/projects/sync/push",
                data={"project_id": str(uuid.uuid4()), "manifest": "{}"},
                files={"zip_file": ("p.zip", io.BytesIO(b"x"), "application/zip")},
            )
        assert resp.status_code == 403


class TestPull:
    async def test_pull_streams_blob(self, client_factory, mock_db, storage):
        from app.permissions import Permission

        user = _user(scopes=[Permission.PROJECTS_SYNC.value])
        project_id = uuid.uuid4()
        _project, access = _mock_project_access(project_id)

        snapshot = MagicMock()
        snapshot.id = uuid.uuid4()
        snapshot.project_id = project_id
        snapshot.sync_blob_key = "key-1"

        mock_db.execute = AsyncMock(return_value=_scalar(snapshot))
        storage.blobs["key-1"] = b"ZIPDATA"

        with patch("app.routers.public.projects_sync.get_project_with_access", new=access):
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.get(f"/api/v1/projects/sync/pull/{snapshot.id}")

        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "application/zip"
        assert resp.content == b"ZIPDATA"


class TestManifest:
    async def test_manifest_returns_latest(self, client_factory, mock_db, storage):
        from app.permissions import Permission

        user = _user(scopes=[Permission.PROJECTS_SYNC.value])
        project_id = uuid.uuid4()
        _project, access = _mock_project_access(project_id)

        current = MagicMock()
        current.id = uuid.uuid4()
        current.sync_manifest = {"a.txt": "h1"}
        current.created_at = datetime(2026, 4, 13)

        mock_db.execute = AsyncMock(return_value=_scalar(current))

        with patch("app.routers.public.projects_sync.get_project_with_access", new=access):
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.get(f"/api/v1/projects/sync/manifest/{project_id}")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["manifest"] == {"a.txt": "h1"}
        assert body["snapshot_id"] == str(current.id)


class TestHistory:
    async def test_history_paginated(self, client_factory, mock_db, storage):
        from app.permissions import Permission

        user = _user(scopes=[Permission.PROJECTS_SYNC.value])
        project_id = uuid.uuid4()
        _project, access = _mock_project_access(project_id)

        rows = []
        for i in range(2):
            r = MagicMock()
            r.id = uuid.uuid4()
            r.label = f"snap-{i}"
            r.sync_size_bytes = 100 + i
            r.sync_blob_key = f"key-{i}"
            r.created_at = datetime(2026, 4, 13, 0, i)
            rows.append(r)

        mock_db.execute = AsyncMock(side_effect=[_scalar(2), _scalars(rows)])

        with patch("app.routers.public.projects_sync.get_project_with_access", new=access):
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.get(f"/api/v1/projects/sync/history/{project_id}")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2
        assert "etag" in resp.headers
