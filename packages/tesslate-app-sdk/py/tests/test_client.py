from __future__ import annotations

import json

import httpx
import pytest
import respx

from tesslate_app_sdk import AppClient, AppSdkOptions, ManifestBuilder
from tesslate_app_sdk.client import AppSdkHttpError

BASE = "https://studio.example.com"
API_KEY = "tsk_test_abc123"


def _opts() -> AppSdkOptions:
    return AppSdkOptions(base_url=BASE, api_key=API_KEY)


def test_rejects_bad_api_key() -> None:
    with pytest.raises(ValueError):
        AppSdkOptions(base_url=BASE, api_key="nope")


@respx.mock
async def test_publish_version_sends_expected_request() -> None:
    route = respx.post(f"{BASE}/api/app-versions/publish").mock(
        return_value=httpx.Response(
            201,
            json={
                "app_id": "a",
                "app_version_id": "v",
                "version": "1.0.0",
                "bundle_hash": "bh",
                "manifest_hash": "mh",
                "submission_id": "s",
            },
        )
    )
    manifest = (
        ManifestBuilder()
        .app(slug="hello", name="Hello", version="0.1.0")
        .surface(kind="iframe", entry="index.html")
        .billing(model="wallet-mix", default_budget_usd=0.5)
        .require_features(["apps.v1"])
        .build()
    )
    async with AppClient(_opts()) as client:
        result = await client.publish_version(project_id="proj-1", manifest=manifest)

    assert result["app_id"] == "a"
    req = route.calls.last.request
    assert req.headers["authorization"] == f"Bearer {API_KEY}"
    assert req.headers["content-type"].startswith("application/json")
    body = json.loads(req.content)
    assert body["project_id"] == "proj-1"
    assert body["manifest"]["manifest_schema_version"] == "2025-01"
    assert body["manifest"]["app"]["slug"] == "hello"
    assert body["app_id"] is None


@respx.mock
async def test_install_app_posts_consents() -> None:
    route = respx.post(f"{BASE}/api/app-installs/install").mock(
        return_value=httpx.Response(
            201,
            json={
                "app_instance_id": "i",
                "project_id": "p",
                "volume_id": "v",
                "node_name": "n",
            },
        )
    )
    async with AppClient(_opts()) as client:
        r = await client.install_app(
            app_version_id="ver",
            team_id="team",
            wallet_mix_consent={"accepted": True},
            mcp_consents=[{"server": "x", "accepted": True}],
            update_policy="patch-auto",
        )
    assert r["app_instance_id"] == "i"
    body = json.loads(route.calls.last.request.content)
    assert body["update_policy"] == "patch-auto"
    assert body["mcp_consents"][0]["server"] == "x"


@respx.mock
async def test_begin_session_and_error_path() -> None:
    respx.post(f"{BASE}/api/apps/runtime/sessions").mock(
        return_value=httpx.Response(
            201,
            json={
                "session_id": "s",
                "app_instance_id": "a",
                "litellm_key_id": "lk",
                "api_key": "sk-...",
                "budget_usd": 1.0,
                "ttl_seconds": 3600,
            },
        )
    )
    async with AppClient(_opts()) as client:
        r = await client.begin_session(app_instance_id="a", budget_usd=1.0, ttl_seconds=3600)
    assert r["session_id"] == "s"
    assert r["api_key"] == "sk-..."

    respx.post(f"{BASE}/api/apps/runtime/sessions").mock(
        return_value=httpx.Response(409, json={"detail": "not runnable"})
    )
    async with AppClient(_opts()) as client:
        with pytest.raises(AppSdkHttpError) as excinfo:
            await client.begin_session(app_instance_id="a")
    assert excinfo.value.status == 409


@respx.mock
async def test_end_session_204_returns_none() -> None:
    respx.delete(f"{BASE}/api/apps/runtime/sessions/sess-1").mock(
        return_value=httpx.Response(204)
    )
    async with AppClient(_opts()) as client:
        result = await client.end_session("sess-1")
    assert result is None


@respx.mock
async def test_get_version_info() -> None:
    respx.get(f"{BASE}/api/version").mock(
        return_value=httpx.Response(
            200,
            json={
                "build_sha": "abc",
                "schema_versions": {"manifest": ["2025-01"]},
                "features": ["apps.v1"],
                "feature_set_hash": "h",
                "runtime_api_supported": ["2025-01"],
            },
        )
    )
    async with AppClient(_opts()) as client:
        v = await client.get_version_info()
    assert v["build_sha"] == "abc"
    assert v["schema_versions"]["manifest"] == ["2025-01"]


@respx.mock
async def test_check_compat() -> None:
    route = respx.post(f"{BASE}/api/version/check-compat").mock(
        return_value=httpx.Response(
            200,
            json={
                "compatible": True,
                "missing": [],
                "manifest_schema_supported": ["2025-01"],
                "upgrade_required": False,
                "feature_set_hash": "h",
            },
        )
    )
    async with AppClient(_opts()) as client:
        r = await client.check_compat(
            required_features=["apps.v1"], manifest_schema="2025-01"
        )
    assert r["compatible"] is True
    body = json.loads(route.calls.last.request.content)
    assert body["manifest_schema"] == "2025-01"
