"""TestClient coverage for the desktop tray/runtime-probe router."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.routers import desktop
from app.services.runtime_probe import ProbeResult
from app.users import current_active_user


@pytest.fixture
def app_with_desktop_router():
    app = FastAPI()
    app.include_router(desktop.router)

    fake_user = Mock()
    fake_user.id = "00000000-0000-0000-0000-000000000001"
    app.dependency_overrides[current_active_user] = lambda: fake_user

    class _StubResult:
        def scalars(self):
            return self

        def all(self):
            return []

    class _StubSession:
        async def execute(self, _stmt):
            return _StubResult()

    async def _stub_db():
        yield _StubSession()

    app.dependency_overrides[get_db] = _stub_db
    return app


@pytest.fixture
def client(app_with_desktop_router):
    return TestClient(app_with_desktop_router)


@pytest.fixture
def stub_probe(monkeypatch):
    probe = Mock()
    probe.local_available = AsyncMock(return_value=ProbeResult(ok=True))
    probe.docker_available = AsyncMock(
        return_value=ProbeResult(ok=False, reason="Docker daemon unreachable")
    )
    probe.k8s_remote_available = AsyncMock(
        return_value=ProbeResult(ok=False, reason="Cloud pairing required")
    )
    monkeypatch.setattr(desktop, "get_runtime_probe", lambda: probe)
    return probe


def test_runtime_probe_shape(client, stub_probe):
    resp = client.get("/api/desktop/runtime-probe")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"local", "docker", "k8s"}
    assert body["local"] == {"ok": True, "reason": None}
    assert body["docker"]["ok"] is False
    assert body["docker"]["reason"] == "Docker daemon unreachable"
    assert body["k8s"]["ok"] is False


def test_tray_state_shape(client, stub_probe):
    resp = client.get("/api/desktop/tray-state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["running_projects"] == []
    assert body["running_agents"] == []
    assert set(body["runtimes"].keys()) == {"local", "docker", "k8s"}


def test_probe_exception_is_non_blocking(client, monkeypatch):
    probe = Mock()
    probe.local_available = AsyncMock(return_value=ProbeResult(ok=True))
    probe.docker_available = AsyncMock(side_effect=RuntimeError("boom"))
    probe.k8s_remote_available = AsyncMock(return_value=ProbeResult(ok=False, reason="x"))
    monkeypatch.setattr(desktop, "get_runtime_probe", lambda: probe)

    resp = client.get("/api/desktop/runtime-probe")
    assert resp.status_code == 200
    body = resp.json()
    assert body["docker"]["ok"] is False
    assert body["docker"]["reason"]


def test_tray_state_populates_running_projects_and_agents(app_with_desktop_router, stub_probe):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    now = datetime.now(timezone.utc)
    project_row = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000010",
        slug="demo",
        name="Demo",
        runtime="local",
        last_activity=now,
    )
    agent_row = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000020",
        ref_id="TSK-0001",
        title="Write tests",
        status="running",
        project_id="00000000-0000-0000-0000-000000000010",
        created_at=now,
    )

    class _ProjectResult:
        def scalars(self):
            return self

        def all(self):
            return [project_row]

    class _AgentResult:
        def all(self):
            return [(agent_row, "demo", "Demo")]

    class _Session:
        def __init__(self):
            self._calls = 0

        async def execute(self, _stmt):
            self._calls += 1
            return _ProjectResult() if self._calls == 1 else _AgentResult()

    async def _stub_db():
        yield _Session()

    app_with_desktop_router.dependency_overrides[get_db] = _stub_db

    with TestClient(app_with_desktop_router) as client:
        resp = client.get("/api/desktop/tray-state")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["running_projects"]) == 1
    assert body["running_projects"][0]["slug"] == "demo"
    assert len(body["running_agents"]) == 1
    assert body["running_agents"][0]["ref_id"] == "TSK-0001"
    assert body["running_agents"][0]["project_slug"] == "demo"


def test_tray_state_probe_exception_is_non_blocking(client, monkeypatch):
    probe = Mock()
    probe.local_available = AsyncMock(side_effect=RuntimeError("boom"))
    probe.docker_available = AsyncMock(return_value=ProbeResult(ok=False, reason="x"))
    probe.k8s_remote_available = AsyncMock(return_value=ProbeResult(ok=False, reason="x"))
    monkeypatch.setattr(desktop, "get_runtime_probe", lambda: probe)

    resp = client.get("/api/desktop/tray-state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["runtimes"]["local"]["ok"] is False
