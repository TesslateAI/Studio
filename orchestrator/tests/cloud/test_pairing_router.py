"""Pairing endpoints on /api/desktop/auth/*."""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TESSLATE_STUDIO_HOME", str(tmp_path))
    monkeypatch.delenv("TESSLATE_CLOUD_TOKEN", raising=False)
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)

    from app.config import get_settings
    from app.routers import desktop
    from app.users import current_active_user

    get_settings.cache_clear()

    fake_user = Mock()
    fake_user.id = uuid.uuid4()

    app = FastAPI()
    app.include_router(desktop.router)
    app.dependency_overrides[current_active_user] = lambda: fake_user

    yield TestClient(app)
    get_settings.cache_clear()


def test_status_unpaired(app_client: TestClient) -> None:
    r = app_client.get("/api/desktop/auth/status")
    assert r.status_code == 200
    body = r.json()
    assert body["paired"] is False
    assert "cloud_url" in body


def test_set_then_status_then_clear(app_client: TestClient) -> None:
    r = app_client.post("/api/desktop/auth/token", json={"token": "tsk_abc"})
    assert r.status_code == 200
    assert r.json() == {"paired": True}

    r = app_client.get("/api/desktop/auth/status")
    assert r.json()["paired"] is True

    r = app_client.delete("/api/desktop/auth/token")
    assert r.status_code == 200
    assert r.json() == {"paired": False}

    r = app_client.get("/api/desktop/auth/status")
    assert r.json()["paired"] is False


def test_set_rejects_empty_token(app_client: TestClient) -> None:
    r = app_client.post("/api/desktop/auth/token", json={"token": ""})
    assert r.status_code == 422
