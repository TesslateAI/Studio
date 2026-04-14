"""Integration tests for /api/v1/agents/handoff/* endpoints."""
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


def _mock_project_access():
    project = MagicMock()
    project.id = uuid.uuid4()
    project.slug = "proj"
    project.visibility = "private"
    project.team_id = None

    async def _access(db, slug, user_id, permission):
        return project, "admin"

    return project, _access


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.fixture
def mock_arq_pool():
    pool = MagicMock()
    pool.enqueue_job = AsyncMock()
    return pool


@pytest.fixture
def mock_task_manager():
    tm = MagicMock()
    tm.create_task = MagicMock()
    tm.update_task_status = AsyncMock()
    tm.get_task_async = AsyncMock()
    return tm


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


class TestUpload:
    async def test_upload_requires_scope(self, client_factory):
        from app.permissions import Permission

        user = _user(scopes=[Permission.MARKETPLACE_READ.value])
        client = await client_factory(user)
        async with client as ac:
            resp = await ac.post(
                "/api/v1/agents/handoff/upload",
                json={
                    "project_id": str(uuid.uuid4()),
                    "chat_id": str(uuid.uuid4()),
                    "message": "hi",
                },
            )
        assert resp.status_code == 403

    async def test_upload_enqueues_new_task(
        self, client_factory, mock_arq_pool, mock_task_manager
    ):
        from app.permissions import Permission

        user = _user(
            scopes=[Permission.AGENTS_HANDOFF.value, Permission.PROJECT_EDIT.value]
        )
        project, access = _mock_project_access()

        with patch(
            "app.routers.public.agents_handoff.get_project_with_access", new=access
        ), patch(
            "app.routers.public.agents_handoff._get_arq_pool",
            new=AsyncMock(return_value=mock_arq_pool),
        ), patch(
            "app.routers.public.agents_handoff.get_task_manager",
            return_value=mock_task_manager,
        ):
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.post(
                    "/api/v1/agents/handoff/upload",
                    json={
                        "project_id": str(project.id),
                        "chat_id": str(uuid.uuid4()),
                        "message": "resume work",
                        "trajectory": [{"response_text": "prior"}],
                        "skill_bindings": ["search"],
                    },
                )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "queued"
        assert uuid.UUID(body["task_id"])
        mock_arq_pool.enqueue_job.assert_awaited_once()
        mock_task_manager.create_task.assert_called_once()

    async def test_upload_503_when_redis_unavailable(
        self, client_factory, mock_task_manager
    ):
        from app.permissions import Permission

        user = _user(
            scopes=[Permission.AGENTS_HANDOFF.value, Permission.PROJECT_EDIT.value]
        )
        project, access = _mock_project_access()

        with patch(
            "app.routers.public.agents_handoff.get_project_with_access", new=access
        ), patch(
            "app.routers.public.agents_handoff._get_arq_pool",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.routers.public.agents_handoff.get_task_manager",
            return_value=mock_task_manager,
        ):
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.post(
                    "/api/v1/agents/handoff/upload",
                    json={
                        "project_id": str(project.id),
                        "chat_id": str(uuid.uuid4()),
                        "message": "x",
                    },
                )
        assert resp.status_code == 503


class TestDownload:
    async def test_download_returns_bundle(self, client_factory, mock_db, mock_task_manager):
        from app.permissions import Permission
        from app.services.task_manager import TaskStatus

        user = _user(scopes=[Permission.AGENTS_HANDOFF.value])
        chat_id = uuid.uuid4()
        project_id = uuid.uuid4()

        task = MagicMock()
        task.id = "t-1"
        task.user_id = user.id
        task.status = TaskStatus.RUNNING
        task.metadata = {
            "chat_id": str(chat_id),
            "project_id": str(project_id),
            "message": "hello",
        }
        mock_task_manager.get_task_async = AsyncMock(return_value=task)

        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=result)

        with patch(
            "app.routers.public.agents_handoff.get_task_manager",
            return_value=mock_task_manager,
        ):
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.get("/api/v1/agents/handoff/download/t-1")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["task_id"] == "t-1"
        assert body["chat_id"] == str(chat_id)
        assert body["trajectory"] == []

    async def test_download_404_when_task_missing(self, client_factory, mock_task_manager):
        from app.permissions import Permission

        user = _user(scopes=[Permission.AGENTS_HANDOFF.value])
        mock_task_manager.get_task_async = AsyncMock(return_value=None)

        with patch(
            "app.routers.public.agents_handoff.get_task_manager",
            return_value=mock_task_manager,
        ):
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.get("/api/v1/agents/handoff/download/missing")
        assert resp.status_code == 404


class TestPause:
    async def test_pause_signals_cancel(self, client_factory, mock_task_manager):
        from app.permissions import Permission
        from app.services.task_manager import TaskStatus

        user = _user(scopes=[Permission.AGENTS_HANDOFF.value])
        task = MagicMock()
        task.id = "t-1"
        task.user_id = user.id
        task.status = TaskStatus.RUNNING
        task.metadata = {"project_id": str(uuid.uuid4())}
        mock_task_manager.get_task_async = AsyncMock(return_value=task)

        pubsub = MagicMock()
        pubsub.request_cancellation = AsyncMock()

        with patch(
            "app.routers.public.agents_handoff.get_task_manager",
            return_value=mock_task_manager,
        ), patch("app.services.pubsub.get_pubsub", return_value=pubsub):
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.post("/api/v1/agents/handoff/t-1/pause")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["paused"] is True
        assert body["status"] == "cancelled"
        pubsub.request_cancellation.assert_awaited_once_with("t-1")

    async def test_pause_noop_on_terminal_task(self, client_factory, mock_task_manager):
        from app.permissions import Permission
        from app.services.task_manager import TaskStatus

        user = _user(scopes=[Permission.AGENTS_HANDOFF.value])
        task = MagicMock()
        task.id = "t-1"
        task.user_id = user.id
        task.status = TaskStatus.COMPLETED
        task.metadata = {}
        mock_task_manager.get_task_async = AsyncMock(return_value=task)

        with patch(
            "app.routers.public.agents_handoff.get_task_manager",
            return_value=mock_task_manager,
        ):
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.post("/api/v1/agents/handoff/t-1/pause")
        assert resp.status_code == 200
        body = resp.json()
        assert body["paused"] is False


class TestResume:
    async def test_resume_enqueues_new_task_from_paused(
        self, client_factory, mock_db, mock_arq_pool, mock_task_manager
    ):
        from app.permissions import Permission
        from app.services.task_manager import TaskStatus

        user = _user(
            scopes=[Permission.AGENTS_HANDOFF.value, Permission.PROJECT_EDIT.value]
        )
        chat_id = uuid.uuid4()
        project, access = _mock_project_access()

        task = MagicMock()
        task.id = "paused-1"
        task.user_id = user.id
        task.status = TaskStatus.CANCELLED
        task.metadata = {
            "chat_id": str(chat_id),
            "project_id": str(project.id),
            "message": "stuck here",
        }
        mock_task_manager.get_task_async = AsyncMock(return_value=task)

        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=result)

        with patch(
            "app.routers.public.agents_handoff.get_project_with_access", new=access
        ), patch(
            "app.routers.public.agents_handoff._get_arq_pool",
            new=AsyncMock(return_value=mock_arq_pool),
        ), patch(
            "app.routers.public.agents_handoff.get_task_manager",
            return_value=mock_task_manager,
        ):
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.post("/api/v1/agents/handoff/paused-1/resume")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "queued"
        new_id = body["task_id"]
        assert new_id != "paused-1"
        mock_arq_pool.enqueue_job.assert_awaited_once()
