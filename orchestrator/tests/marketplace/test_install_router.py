"""Desktop marketplace install router: POST/DELETE + error mapping."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def opensail_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OPENSAIL_HOME", str(tmp_path))
    monkeypatch.delenv("TESSLATE_CLOUD_TOKEN", raising=False)
    for sub in ("agents", "skills", "bases", "themes", "cache"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    from app.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def app_client(opensail_home: Path, monkeypatch: pytest.MonkeyPatch):
    from app.routers import marketplace_local
    from app.services import cloud_client as cc_mod
    from app.users import current_active_user

    fake_user = Mock()
    fake_user.id = uuid.uuid4()

    app = FastAPI()
    app.include_router(marketplace_local.router)
    app.dependency_overrides[current_active_user] = lambda: fake_user

    async def _no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(cc_mod.CloudClient, "_sleep", staticmethod(_no_sleep))

    holder: dict[str, cc_mod.CloudClient] = {}

    async def fake_get():
        if "c" not in holder:
            holder["c"] = cc_mod.CloudClient(base_url="https://cloud.test")
        return holder["c"]

    monkeypatch.setattr("app.services.marketplace_installer.get_cloud_client", fake_get)

    yield TestClient(app)


@pytest.fixture
def paired():
    from app.services import token_store

    token_store.set_cloud_token("tsk_test")
    yield
    token_store.clear_cloud_token()


def test_install_happy_path(app_client: TestClient, opensail_home: Path, paired) -> None:
    payload = b"file contents"
    sha = _sha(payload)

    with respx.mock(assert_all_called=False) as router:
        router.post("https://cloud.test/api/v1/marketplace/install").mock(
            return_value=httpx.Response(
                200,
                json={
                    "install_id": "inst-rt",
                    "download_urls": [{"url": "https://cdn.test/a", "sha256": sha, "name": "a"}],
                    "manifest": {"slug": "agt", "name": "Agent", "version": "1"},
                },
            )
        )
        router.get("https://cdn.test/a").mock(return_value=httpx.Response(200, content=payload))
        router.post("https://cloud.test/api/v1/marketplace/install/inst-rt/ack").mock(
            return_value=httpx.Response(200, json={})
        )

        r = app_client.post(
            "/api/desktop/marketplace/install",
            json={"kind": "agent", "slug": "agt"},
        )

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["install_id"] == "inst-rt"
    assert body["slug"] == "agt"
    assert (opensail_home / "agents" / "agt" / "manifest.json").is_file()


def test_install_duplicate_returns_409(app_client: TestClient, opensail_home: Path, paired) -> None:
    (opensail_home / "skills" / "dup").mkdir(parents=True)
    r = app_client.post(
        "/api/desktop/marketplace/install",
        json={"kind": "skill", "slug": "dup"},
    )
    assert r.status_code == 409


def test_install_unpaired_returns_401(app_client: TestClient, opensail_home: Path) -> None:
    # No token set → CloudClient raises NotPairedError on build_headers.
    r = app_client.post(
        "/api/desktop/marketplace/install",
        json={"kind": "skill", "slug": "ne"},
    )
    assert r.status_code == 401


def test_install_circuit_open_returns_502(
    app_client: TestClient, opensail_home: Path, paired, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import marketplace_installer
    from app.services.cloud_client import CircuitOpenError

    async def _raise(*_a, **_k):
        raise CircuitOpenError("open")

    monkeypatch.setattr(marketplace_installer, "_initiate_install", _raise)

    r = app_client.post(
        "/api/desktop/marketplace/install",
        json={"kind": "base", "slug": "b1"},
    )
    assert r.status_code == 502


def test_delete_happy_path(app_client: TestClient, opensail_home: Path) -> None:
    target = opensail_home / "themes" / "t1"
    target.mkdir(parents=True)
    (target / "manifest.json").write_text("{}")

    # Seed cache so we can verify invalidation.
    cache = opensail_home / "cache" / "marketplace.json"
    cache.write_text(json.dumps({"theme": {"ts": 0, "items": [{"slug": "t1"}]}}))

    r = app_client.delete("/api/desktop/marketplace/install/theme/t1")
    assert r.status_code == 204
    assert not target.exists()

    blob = json.loads(cache.read_text())
    assert "theme" not in blob


def test_delete_missing_returns_404(app_client: TestClient, opensail_home: Path) -> None:
    r = app_client.delete("/api/desktop/marketplace/install/agent/missing")
    assert r.status_code == 404
