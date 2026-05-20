"""Desktop cloud-url + first-run endpoints (/api/desktop)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("OPENSAIL_HOME", str(tmp_path))
    monkeypatch.delenv("TESSLATE_CLOUD_URL", raising=False)
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)

    from app.routers import desktop
    from app.services.desktop_auth import _LoopbackUser, desktop_loopback_or_session

    app = FastAPI()
    app.include_router(desktop.router)
    app.dependency_overrides[desktop_loopback_or_session] = lambda: _LoopbackUser()
    return TestClient(app)


def test_set_cloud_url_valid(client: TestClient) -> None:
    resp = client.put("/api/desktop/cloud-url", json={"url": "https://cloud.example.com/"})
    assert resp.status_code == 200
    assert resp.json()["cloud_url"] == "https://cloud.example.com"

    status = client.get("/api/desktop/auth/status").json()
    assert status["cloud_url"] == "https://cloud.example.com"
    assert status["default_cloud_url"].startswith("http")


def test_set_cloud_url_invalid_rejected(client: TestClient) -> None:
    resp = client.put("/api/desktop/cloud-url", json={"url": "ftp://nope"})
    assert resp.status_code == 400


def test_clear_cloud_url_reverts_to_default(client: TestClient) -> None:
    client.put("/api/desktop/cloud-url", json={"url": "https://cloud.example.com"})
    default = client.get("/api/desktop/auth/status").json()["default_cloud_url"]

    resp = client.delete("/api/desktop/cloud-url")
    assert resp.status_code == 200
    assert resp.json()["cloud_url"] == default


def test_first_run_lifecycle(client: TestClient) -> None:
    assert client.get("/api/desktop/first-run").json() == {"completed": False}

    assert client.post("/api/desktop/first-run").json() == {"completed": True}
    assert client.get("/api/desktop/first-run").json() == {"completed": True}
