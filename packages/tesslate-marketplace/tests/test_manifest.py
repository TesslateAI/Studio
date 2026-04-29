"""Manifest exposes hub_id, capabilities, policies, and per-kind sizes."""

from __future__ import annotations


async def test_manifest_shape(client):
    r = await client.get("/v1/manifest")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["api_version"] == "v1"
    assert body["display_name"]
    assert "capabilities" in body and len(body["capabilities"]) >= 5
    assert body["policies"]["max_bundle_size_bytes"]["agent"] == 52_428_800
    assert body["policies"]["max_bundle_size_bytes"]["app"] == 524_288_000
    assert body["policies"]["max_bundle_size_bytes"]["mcp_server"] == 1_048_576
    assert "tar.zst" in body["policies"]["supported_archive_formats"]
    assert "agent" in body["kinds"]
    # Header
    assert r.headers["X-Tesslate-Hub-Id"] == body["hub_id"]
    assert r.headers["X-Tesslate-Hub-Api-Version"] == "v1"


async def test_manifest_advertises_default_caps(client):
    r = await client.get("/v1/manifest")
    body = r.json()
    expected = {"catalog.read", "catalog.changes", "bundles.signed_url", "publish", "yanks", "yanks.feed"}
    assert expected.issubset(set(body["capabilities"]))
