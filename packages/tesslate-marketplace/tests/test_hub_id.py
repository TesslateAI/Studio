"""Hub identity headers are stable across requests + persisted across reboots."""

from __future__ import annotations

import httpx
import pytest


async def test_hub_id_header_present(client):
    r1 = await client.get("/v1/manifest")
    r2 = await client.get("/v1/items?kind=agent")
    assert r1.headers["X-Tesslate-Hub-Id"]
    assert r1.headers["X-Tesslate-Hub-Id"] == r2.headers["X-Tesslate-Hub-Id"]


@pytest.mark.asyncio
async def test_hub_id_persists_across_reboots(env):
    from app.main import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        first = (await c.get("/v1/manifest")).headers["X-Tesslate-Hub-Id"]

    # Simulate a reboot by clearing caches but keeping the on-disk hub_id file.
    from app.services.hub_id import reset_hub_id_cache

    reset_hub_id_cache()
    app2 = create_app()
    transport2 = httpx.ASGITransport(app=app2)
    async with httpx.AsyncClient(transport=transport2, base_url="http://testserver") as c:
        second = (await c.get("/v1/manifest")).headers["X-Tesslate-Hub-Id"]

    assert first == second
