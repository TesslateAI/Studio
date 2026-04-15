"""Tests for /api/version and /api/version/check-compat.

These tests exercise the router directly via ASGI client; they do not
require the full app stack.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.routers.version import router


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


@pytest.fixture
async def client(app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_get_version_shape(client: AsyncClient) -> None:
    r = await client.get("/api/version")
    assert r.status_code == 200
    body = r.json()
    assert "build_sha" in body
    assert body["schema_versions"]["manifest"] == ["2025-01"]
    assert isinstance(body["features"], list)
    assert len(body["feature_set_hash"]) == 64
    assert body["runtime_api_supported"] == ["1.0"]


async def test_get_version_always_on_features_present(client: AsyncClient) -> None:
    r = await client.get("/api/version")
    features = set(r.json()["features"])
    assert {"cas_bundle", "volume_fork", "volume_snapshot"}.issubset(features)


async def test_check_compat_accepts_supported_schema(client: AsyncClient) -> None:
    r = await client.post(
        "/api/version/check-compat",
        json={"manifest_schema": "2025-01", "required_features": ["cas_bundle"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["compatible"] is True
    assert body["missing"] == []
    assert body["upgrade_required"] is False


async def test_check_compat_rejects_unsupported_schema(client: AsyncClient) -> None:
    r = await client.post(
        "/api/version/check-compat",
        json={"manifest_schema": "2099-01", "required_features": []},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["compatible"] is False
    assert body["upgrade_required"] is True
    assert "2025-01" in body["manifest_schema_supported"]


async def test_check_compat_reports_missing_features(client: AsyncClient) -> None:
    r = await client.post(
        "/api/version/check-compat",
        json={
            "manifest_schema": "2025-01",
            "required_features": ["cas_bundle", "made_up_feature_xyz"],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["compatible"] is False
    assert body["missing"] == ["made_up_feature_xyz"]
    assert body["upgrade_required"] is False


async def test_check_compat_empty_required_is_compatible(client: AsyncClient) -> None:
    r = await client.post(
        "/api/version/check-compat",
        json={"manifest_schema": "2025-01", "required_features": []},
    )
    assert r.json()["compatible"] is True
