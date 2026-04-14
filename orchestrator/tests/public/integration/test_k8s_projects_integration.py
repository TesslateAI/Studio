"""Integration tests for /api/v1/k8s/projects/* endpoints."""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

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
    db.refresh = AsyncMock()
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


def _mock_project_access(slug="proj"):
    project = MagicMock()
    project.id = uuid.uuid4()
    project.slug = slug
    project.owner_id = uuid.uuid4()
    project.team_id = None
    project.visibility = "private"

    async def _access(db, slug_arg, user_id, permission):
        return project, "admin"

    return project, _access


def _container(name="web"):
    c = MagicMock()
    c.id = uuid.uuid4()
    c.name = name
    return c


@pytest.fixture
def mock_orchestrator():
    orch = MagicMock()
    orch.start_project = AsyncMock(
        return_value={"status": "running", "containers": {"web": "http://web"}, "namespace": "proj-ns"}
    )
    orch.stop_project = AsyncMock(return_value=None)
    orch.restart_project = AsyncMock(
        return_value={"status": "running", "containers": {"web": "http://web"}, "namespace": "proj-ns"}
    )
    orch.get_project_status = AsyncMock(return_value={"web": {"phase": "Running", "ready": True}})
    orch.delete_project_namespace = AsyncMock(return_value=None)
    return orch


class TestLifecycle:
    async def test_start_requires_scope(self, client_factory, mock_db):
        from app.permissions import Permission

        user = _user(scopes=[Permission.MARKETPLACE_READ.value])
        client = await client_factory(user)
        async with client as ac:
            resp = await ac.post("/api/v1/k8s/projects", json={"project_id": str(uuid.uuid4())})
        assert resp.status_code == 403

    async def test_create_or_start_starts_project(self, client_factory, mock_db, mock_orchestrator):
        from app.permissions import Permission

        user = _user(
            scopes=[Permission.K8S_PROJECTS.value, Permission.CONTAINER_START_STOP.value]
        )
        project, access = _mock_project_access()
        mock_db.execute = AsyncMock(side_effect=[_scalars([_container()]), _scalars([])])

        with patch("app.routers.public.k8s_projects.get_project_with_access", new=access), \
             patch("app.routers.public.k8s_projects.get_orchestrator", return_value=mock_orchestrator):
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.post(
                    "/api/v1/k8s/projects", json={"project_id": str(project.id)}
                )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "running"
        assert body["containers"] == {"web": "http://web"}
        mock_orchestrator.start_project.assert_awaited_once()

    async def test_create_or_start_rejects_empty_project(
        self, client_factory, mock_db, mock_orchestrator
    ):
        from app.permissions import Permission

        user = _user(
            scopes=[Permission.K8S_PROJECTS.value, Permission.CONTAINER_START_STOP.value]
        )
        project, access = _mock_project_access()
        mock_db.execute = AsyncMock(side_effect=[_scalars([]), _scalars([])])

        with patch("app.routers.public.k8s_projects.get_project_with_access", new=access), \
             patch("app.routers.public.k8s_projects.get_orchestrator", return_value=mock_orchestrator):
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.post(
                    "/api/v1/k8s/projects", json={"project_id": str(project.id)}
                )
        assert resp.status_code == 400

    async def test_stop_project(self, client_factory, mock_db, mock_orchestrator):
        from app.permissions import Permission

        user = _user(
            scopes=[Permission.K8S_PROJECTS.value, Permission.CONTAINER_START_STOP.value]
        )
        project, access = _mock_project_access()

        with patch("app.routers.public.k8s_projects.get_project_with_access", new=access), \
             patch("app.routers.public.k8s_projects.get_orchestrator", return_value=mock_orchestrator):
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.post(f"/api/v1/k8s/projects/{project.slug}/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"
        mock_orchestrator.stop_project.assert_awaited_once()

    async def test_restart_project(self, client_factory, mock_db, mock_orchestrator):
        from app.permissions import Permission

        user = _user(
            scopes=[Permission.K8S_PROJECTS.value, Permission.CONTAINER_START_STOP.value]
        )
        project, access = _mock_project_access()
        mock_db.execute = AsyncMock(side_effect=[_scalars([_container()]), _scalars([])])

        with patch("app.routers.public.k8s_projects.get_project_with_access", new=access), \
             patch("app.routers.public.k8s_projects.get_orchestrator", return_value=mock_orchestrator):
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.post(f"/api/v1/k8s/projects/{project.slug}/restart")
        assert resp.status_code == 200
        mock_orchestrator.restart_project.assert_awaited_once()

    async def test_get_status(self, client_factory, mock_db, mock_orchestrator):
        from app.permissions import Permission

        user = _user(scopes=[Permission.K8S_PROJECTS.value])
        project, access = _mock_project_access()

        with patch("app.routers.public.k8s_projects.get_project_with_access", new=access), \
             patch("app.routers.public.k8s_projects.get_orchestrator", return_value=mock_orchestrator):
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.get(f"/api/v1/k8s/projects/{project.slug}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["project_slug"] == project.slug
        assert body["status"] == {"web": {"phase": "Running", "ready": True}}

    async def test_delete_runtime_stops_and_tears_down(
        self, client_factory, mock_db, mock_orchestrator
    ):
        from app.permissions import Permission

        user = _user(
            scopes=[Permission.K8S_PROJECTS.value, Permission.PROJECT_DELETE.value]
        )
        project, access = _mock_project_access()

        with patch("app.routers.public.k8s_projects.get_project_with_access", new=access), \
             patch("app.routers.public.k8s_projects.get_orchestrator", return_value=mock_orchestrator):
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.delete(f"/api/v1/k8s/projects/{project.slug}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "released"
        mock_orchestrator.stop_project.assert_awaited_once()
        mock_orchestrator.delete_project_namespace.assert_awaited_once()


class TestStreams:
    async def test_status_event_stream_emits_frame(self, mock_orchestrator):
        from app.routers.public.k8s_projects import _status_event_stream

        gen = _status_event_stream(mock_orchestrator, "proj", uuid.uuid4(), interval=0.01)
        frame = await gen.__anext__()
        await gen.aclose()
        assert frame.startswith("id: 0\ndata: ")
        assert '"cursor": 0' in frame
        assert "phase" in frame

    async def test_logs_404_when_container_missing(
        self, client_factory, mock_db, mock_orchestrator
    ):
        from app.permissions import Permission

        user = _user(scopes=[Permission.K8S_PROJECTS.value])
        project, access = _mock_project_access()
        mock_db.execute = AsyncMock(return_value=_scalar(None))

        with patch("app.routers.public.k8s_projects.get_project_with_access", new=access), \
             patch("app.routers.public.k8s_projects.get_orchestrator", return_value=mock_orchestrator):
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.get(f"/api/v1/k8s/projects/{project.slug}/logs/missing")
        assert resp.status_code == 404
