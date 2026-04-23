"""Router coverage for /api/desktop/projects/{id}/sync/{push,pull,status}."""

from __future__ import annotations

import io
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def opensail_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OPENSAIL_HOME", str(tmp_path))
    monkeypatch.delenv("TESSLATE_CLOUD_TOKEN", raising=False)
    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)
    from app.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def paired():
    from app.services import token_store

    token_store.set_cloud_token("tsk_test")
    yield
    token_store.clear_cloud_token()


@pytest.fixture
def client(tmp_path: Path, opensail_home: Path, monkeypatch: pytest.MonkeyPatch):
    from app.database import get_db
    from app.routers import desktop as desktop_mod
    from app.services import cloud_client as cc_mod
    from app.users import current_active_user

    fake_user = Mock()
    fake_user.id = uuid.uuid4()

    # Stand up a project directory the sync client can read/write to.
    proj_root = tmp_path / "srcproj"
    proj_root.mkdir()
    (proj_root / "hello.txt").write_text("world")

    fake_project = SimpleNamespace(
        id=PROJECT_ID,
        slug="proj",
        owner_id=fake_user.id,
        source_path=str(proj_root),
        last_sync_at=None,
    )

    async def fake_load(project_id, user, db):
        return fake_project

    monkeypatch.setattr(desktop_mod, "_load_project", fake_load)

    async def _no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(cc_mod.CloudClient, "_sleep", staticmethod(_no_sleep))

    holder: dict[str, cc_mod.CloudClient] = {}

    async def fake_get():
        if "c" not in holder:
            holder["c"] = cc_mod.CloudClient(base_url="https://cloud.test")
        return holder["c"]

    monkeypatch.setattr("app.services.sync_client.get_cloud_client", fake_get)
    monkeypatch.setattr("app.services.cloud_client.get_cloud_client", fake_get)

    async def noop_db():
        s = AsyncMock()
        yield s

    app = FastAPI()
    app.include_router(desktop_mod.router)
    app.dependency_overrides[current_active_user] = lambda: fake_user
    app.dependency_overrides[get_db] = noop_db
    yield TestClient(app), fake_project


def test_push_happy_path(client, paired):
    tc, project = client
    pid = str(project.id)

    with respx.mock(assert_all_called=False) as router:
        router.get(f"https://cloud.test/api/v1/projects/sync/manifest/{pid}").mock(
            return_value=httpx.Response(404)
        )
        router.post("https://cloud.test/api/v1/projects/sync/push").mock(
            return_value=httpx.Response(
                200,
                json={
                    "sync_id": "snap-rt",
                    "uploaded_at": "2026-04-14T00:00:00+00:00",
                    "snapshot_id": "snap-rt",
                    "size_bytes": 1,
                },
            )
        )

        r = tc.post(f"/api/desktop/projects/{pid}/sync/push")

    assert r.status_code == 200, r.text
    assert r.json()["sync_id"] == "snap-rt"


def test_push_unpaired_returns_401(client):
    tc, project = client
    pid = str(project.id)
    r = tc.post(f"/api/desktop/projects/{pid}/sync/push")
    assert r.status_code == 401


def test_push_conflict_returns_409(client, paired):
    tc, project = client
    project.last_sync_at = datetime.now(UTC) - timedelta(hours=2)
    pid = str(project.id)

    newer = datetime.now(UTC).isoformat()
    with respx.mock(assert_all_called=False) as router:
        router.get(f"https://cloud.test/api/v1/projects/sync/manifest/{pid}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "project_id": pid,
                    "snapshot_id": "s-remote",
                    "manifest": {},
                    "updated_at": newer,
                },
            )
        )

        r = tc.post(f"/api/desktop/projects/{pid}/sync/push")

    assert r.status_code == 409


def test_push_circuit_open_returns_502(client, paired, monkeypatch):
    from app.services import sync_client as sc
    from app.services.cloud_client import CircuitOpenError

    async def _raise(*_a, **_k):
        raise CircuitOpenError("open")

    monkeypatch.setattr(sc, "push", _raise)

    tc, project = client
    pid = str(project.id)
    r = tc.post(f"/api/desktop/projects/{pid}/sync/push")
    assert r.status_code == 502


def test_pull_happy_path(client, paired):
    tc, project = client
    pid = str(project.id)

    payload = _zip_bytes({"fresh.txt": b"new bytes"})

    with respx.mock(assert_all_called=False) as router:
        router.get(f"https://cloud.test/api/v1/projects/sync/pull/{pid}").mock(
            return_value=httpx.Response(
                200, content=payload, headers={"content-type": "application/zip"}
            )
        )

        r = tc.post(f"/api/desktop/projects/{pid}/sync/pull")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["files_written"] == 1
    assert Path(project.source_path, "fresh.txt").read_bytes() == b"new bytes"


def test_status_degrades_on_cloud_failure(client, paired):
    tc, project = client
    pid = str(project.id)

    with respx.mock(assert_all_called=False) as router:
        router.get(f"https://cloud.test/api/v1/projects/sync/manifest/{pid}").mock(
            return_value=httpx.Response(500)
        )
        r = tc.get(f"/api/desktop/projects/{pid}/sync/status")

    assert r.status_code == 200
    body = r.json()
    assert body["degraded"] is True
    assert body["cloud_updated_at"] is None
