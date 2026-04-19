"""TestClient coverage for the desktop tray/runtime-probe router."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

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
