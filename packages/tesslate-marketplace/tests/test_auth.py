"""Bearer token enforcement on mutating endpoints."""

from __future__ import annotations


async def test_publish_requires_auth(client, env):
    r = await client.post(
        "/v1/publish/agent",
        json={"item": {"slug": "x", "name": "x"}, "version": {"version": "0.1.0"}},
    )
    assert r.status_code == 401


async def test_publish_rejects_unknown_token(client, env):
    r = await client.post(
        "/v1/publish/agent",
        json={"item": {"slug": "x", "name": "x"}, "version": {"version": "0.1.0"}},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert r.status_code == 401


async def test_telemetry_requires_scope(client, env, monkeypatch):
    # Token with publish scope but not telemetry.write
    monkeypatch.setenv("STATIC_TOKENS", "narrow:publish")
    from app.config import reload_settings

    reload_settings()

    r = await client.post(
        "/v1/telemetry/install",
        json={"kind": "agent", "slug": "x"},
        headers={"Authorization": "Bearer narrow"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "insufficient_scope"
