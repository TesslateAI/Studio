"""Disabling a capability returns 501 + typed envelope."""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_unsupported_capability_returns_501(env, monkeypatch, seeded):
    monkeypatch.setenv("DISABLED_CAPABILITIES", "pricing.checkout")
    from app.config import reload_settings

    reload_settings()
    from app.main import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.post(
            "/v1/items/agent/paid-agent/checkout",
            json={"customer_email": "user@example.com"},
        )
        assert r.status_code == 501
        body = r.json()
        assert body["error"] == "unsupported_capability"
        assert body["capability"] == "pricing.checkout"
        assert body["hub_id"] == r.headers["X-Tesslate-Hub-Id"]


@pytest.mark.asyncio
async def test_manifest_excludes_disabled_capability(env, monkeypatch):
    monkeypatch.setenv("DISABLED_CAPABILITIES", "telemetry.opt_in,pricing.checkout")
    from app.config import reload_settings

    reload_settings()
    from app.main import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.get("/v1/manifest")
        body = r.json()
        assert "telemetry.opt_in" not in body["capabilities"]
        assert "pricing.checkout" not in body["capabilities"]
        assert "catalog.read" in body["capabilities"]
