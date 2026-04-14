"""Integration tests for public agents endpoints."""
from __future__ import annotations

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


def _tsk_user(scopes=None, user_id=None):
    u = MagicMock()
    u.id = user_id or uuid.uuid4()
    u.is_active = True
    u.default_team_id = None
    key = MagicMock()
    key.id = uuid.uuid4()
    key.key_prefix = "tsk_test"
    key.scopes = scopes
    u._api_key_record = key
    return u


def _task(user_id, task_id="t1", status_value="running", metadata=None, created_at=None):
    from app.services.task_manager import TaskStatus

    t = MagicMock()
    t.id = task_id
    t.user_id = user_id
    t.type = "agent_execution"
    t.status = TaskStatus(status_value)
    t.created_at = created_at or datetime(2026, 4, 13, 10, 0, 0)
    t.started_at = None
    t.completed_at = None
    t.error = None
    t.metadata = metadata or {"project_id": str(uuid.uuid4()), "chat_id": str(uuid.uuid4()), "origin": "api", "message": "hi"}
    return t


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
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
# GET /api/v1/agents/tasks
# ---------------------------------------------------------------------------


class TestListTasks:
    async def test_list_returns_pagination_envelope(self, client_factory, mock_db):
        from app.permissions import Permission

        user = _tsk_user(scopes=[Permission.AGENTS_READ.value])
        tasks = [_task(user.id, task_id=f"t{i}") for i in range(3)]

        with patch("app.routers.public.agents.get_task_manager") as tm:
            tm.return_value.get_user_tasks_async = AsyncMock(return_value=tasks)
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.get("/api/v1/agents/tasks")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 3
        assert len(body["items"]) == 3
        assert body["items"][0]["task_id"].startswith("t")
        assert "etag" in resp.headers

    async def test_filter_by_status(self, client_factory, mock_db):
        from app.permissions import Permission

        user = _tsk_user(scopes=[Permission.AGENTS_READ.value])
        tasks = [
            _task(user.id, task_id="a", status_value="running"),
            _task(user.id, task_id="b", status_value="completed"),
        ]

        with patch("app.routers.public.agents.get_task_manager") as tm:
            tm.return_value.get_user_tasks_async = AsyncMock(return_value=tasks)
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.get("/api/v1/agents/tasks?status=completed")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["task_id"] == "b"

    async def test_no_scope_returns_403(self, client_factory, mock_db):
        from app.permissions import Permission

        user = _tsk_user(scopes=[Permission.MODELS_PROXY.value])
        client = await client_factory(user)
        async with client as ac:
            resp = await ac.get("/api/v1/agents/tasks")
        assert resp.status_code == 403
        assert Permission.AGENTS_READ.value in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/v1/agents/tasks/{id}/cancel
# ---------------------------------------------------------------------------


class TestCancelTask:
    async def test_cancel_sends_signal_and_updates_status(self, client_factory, mock_db):
        from app.permissions import Permission

        user = _tsk_user(scopes=[Permission.CHAT_SEND.value])
        task = _task(user.id, task_id="target", status_value="running")

        with patch("app.routers.public.agents.get_task_manager") as tm_mod, patch(
            "app.services.pubsub.get_pubsub"
        ) as pubsub_mod:
            tm = tm_mod.return_value
            tm.get_task_async = AsyncMock(return_value=task)
            tm.update_task_status = AsyncMock()

            pubsub = MagicMock()
            pubsub.request_cancellation = AsyncMock()
            pubsub_mod.return_value = pubsub

            client = await client_factory(user)
            async with client as ac:
                resp = await ac.post("/api/v1/agents/tasks/target/cancel")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["cancel_requested"] is True
        assert body["status"] == "cancelled"
        pubsub.request_cancellation.assert_awaited_once_with("target")
        tm.update_task_status.assert_awaited_once()

    async def test_cancel_foreign_task_returns_404(self, client_factory, mock_db):
        from app.permissions import Permission

        user = _tsk_user(scopes=[Permission.CHAT_SEND.value])
        # Task owned by someone else
        task = _task(uuid.uuid4(), task_id="foreign", status_value="running")

        with patch("app.routers.public.agents.get_task_manager") as tm_mod:
            tm_mod.return_value.get_task_async = AsyncMock(return_value=task)
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.post("/api/v1/agents/tasks/foreign/cancel")

        assert resp.status_code == 404

    async def test_cancel_terminal_noop(self, client_factory, mock_db):
        from app.permissions import Permission

        user = _tsk_user(scopes=[Permission.CHAT_SEND.value])
        task = _task(user.id, task_id="done", status_value="completed")

        with patch("app.routers.public.agents.get_task_manager") as tm_mod:
            tm_mod.return_value.get_task_async = AsyncMock(return_value=task)
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.post("/api/v1/agents/tasks/done/cancel")

        assert resp.status_code == 200
        body = resp.json()
        assert body["cancel_requested"] is False
        assert body["reason"] == "terminal"


# ---------------------------------------------------------------------------
# GET /api/v1/agents/tasks/{id}/steps
# ---------------------------------------------------------------------------


class TestTaskSteps:
    async def test_steps_paginated(self, client_factory, mock_db):
        from app.permissions import Permission

        user = _tsk_user(scopes=[Permission.AGENTS_READ.value])
        chat_id = str(uuid.uuid4())
        task = _task(user.id, task_id="t", metadata={"chat_id": chat_id, "project_id": None})

        step_rows = []
        for i in range(3):
            s = MagicMock()
            s.id = uuid.uuid4()
            s.step_index = i
            s.step_data = {"iteration": i}
            s.created_at = datetime(2026, 4, 13, 10, i)
            step_rows.append(s)

        count_result = MagicMock()
        count_result.scalar_one.return_value = 3
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = step_rows
        mock_db.execute = AsyncMock(side_effect=[count_result, list_result])

        with patch("app.routers.public.agents.get_task_manager") as tm_mod:
            tm_mod.return_value.get_task_async = AsyncMock(return_value=task)
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.get("/api/v1/agents/tasks/t/steps")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 3
        assert body["items"][0]["step_index"] == 0
        assert "etag" in resp.headers

    async def test_steps_foreign_task_404(self, client_factory, mock_db):
        from app.permissions import Permission

        user = _tsk_user(scopes=[Permission.AGENTS_READ.value])
        task = _task(uuid.uuid4(), task_id="foreign")

        with patch("app.routers.public.agents.get_task_manager") as tm_mod:
            tm_mod.return_value.get_task_async = AsyncMock(return_value=task)
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.get("/api/v1/agents/tasks/foreign/steps")

        assert resp.status_code == 404
