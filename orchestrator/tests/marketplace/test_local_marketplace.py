"""Local marketplace router: scan, dual-source merge, graceful cloud failure, cache."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _write_local_item(home: Path, kind_dir: str, slug: str, name: str) -> None:
    item_dir = home / kind_dir / slug
    item_dir.mkdir(parents=True, exist_ok=True)
    (item_dir / "manifest.json").write_text(
        json.dumps({"slug": slug, "name": name, "version": "1.0.0"}),
        encoding="utf-8",
    )


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

    # Force a fresh CloudClient per test (fast retries via _sleep override).
    async def _no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(cc_mod.CloudClient, "_sleep", staticmethod(_no_sleep))

    holder: dict[str, cc_mod.CloudClient] = {}

    async def fake_get_cloud_client():
        if "c" not in holder:
            holder["c"] = cc_mod.CloudClient(base_url="https://cloud.test")
        return holder["c"]

    monkeypatch.setattr("app.routers.marketplace_local.get_cloud_client", fake_get_cloud_client)

    yield TestClient(app)


def test_local_only_when_unpaired(app_client: TestClient, opensail_home: Path) -> None:
    _write_local_item(opensail_home, "agents", "local-agent", "Local Agent")
    r = app_client.get("/api/desktop/marketplace/items?kind=agent")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "agent"
    slugs = {i["slug"] for i in body["items"]}
    assert slugs == {"local-agent"}
    assert all(i["source"] == "local" for i in body["items"])


def test_dual_source_merge_when_paired(app_client: TestClient, opensail_home: Path) -> None:
    from app.services import token_store

    token_store.set_cloud_token("tsk_test")
    _write_local_item(opensail_home, "agents", "local-agent", "Local")

    with respx.mock(base_url="https://cloud.test") as router:
        router.get("/api/public/marketplace/agents").mock(
            return_value=httpx.Response(
                200,
                json={"items": [{"slug": "cloud-agent", "name": "Cloud", "version": "2"}]},
            )
        )
        r = app_client.get("/api/desktop/marketplace/items?kind=agent")
    assert r.status_code == 200
    items = r.json()["items"]
    by_slug = {i["slug"]: i for i in items}
    assert by_slug["local-agent"]["source"] == "local"
    assert by_slug["cloud-agent"]["source"] == "cloud"


def test_cloud_500_degrades_to_local(app_client: TestClient, opensail_home: Path) -> None:
    from app.services import token_store

    token_store.set_cloud_token("tsk_test")
    _write_local_item(opensail_home, "skills", "skill-a", "Skill A")

    with respx.mock(base_url="https://cloud.test") as router:
        router.get("/api/public/marketplace/skills").mock(return_value=httpx.Response(500))
        r = app_client.get("/api/desktop/marketplace/items?kind=skill")
    assert r.status_code == 200
    items = r.json()["items"]
    assert {i["slug"] for i in items} == {"skill-a"}
    assert items[0]["source"] == "local"


def test_cache_hit_returns_cached(app_client: TestClient, opensail_home: Path) -> None:
    cache_path = opensail_home / "cache" / "marketplace.json"
    cache_path.write_text(
        json.dumps(
            {
                "theme": {
                    "ts": time.time(),
                    "items": [
                        {
                            "slug": "cached-theme",
                            "name": "Cached",
                            "kind": "theme",
                            "source": "local",
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    r = app_client.get("/api/desktop/marketplace/items?kind=theme")
    assert r.status_code == 200
    body = r.json()
    assert body["cached"] is True
    assert body["items"][0]["slug"] == "cached-theme"


def test_stale_cache_serves_then_refreshes(app_client: TestClient, opensail_home: Path) -> None:
    from app.services import token_store

    token_store.set_cloud_token("tsk_test")
    cache_path = opensail_home / "cache" / "marketplace.json"
    cache_path.write_text(
        json.dumps(
            {
                "base": {
                    "ts": time.time() - 10_000,  # stale
                    "items": [
                        {
                            "slug": "old",
                            "name": "Old",
                            "kind": "base",
                            "source": "local",
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    _write_local_item(opensail_home, "bases", "fresh-base", "Fresh")

    with respx.mock(base_url="https://cloud.test") as router:
        router.get("/api/public/marketplace/bases").mock(
            return_value=httpx.Response(
                200, json={"items": [{"slug": "cloud-base", "name": "Cb", "version": "1"}]}
            )
        )
        r = app_client.get("/api/desktop/marketplace/items?kind=base")
        assert r.status_code == 200
        body = r.json()
        assert body.get("stale") is True
        assert body["items"][0]["slug"] == "old"

    # Background task should have rewritten cache with merged fresh data.
    blob = json.loads(cache_path.read_text(encoding="utf-8"))
    refreshed_slugs = {i["slug"] for i in blob["base"]["items"]}
    assert {"fresh-base", "cloud-base"}.issubset(refreshed_slugs)
