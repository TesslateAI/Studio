"""List, detail, versions endpoints."""

from __future__ import annotations


async def test_list_items_filtered_by_kind(client, seeded):
    r = await client.get("/v1/items", params={"kind": "agent"})
    assert r.status_code == 200, r.text
    body = r.json()
    slugs = {item["slug"] for item in body["items"]}
    assert {"tesslate-agent", "agent-builder", "paid-agent"}.issubset(slugs)
    assert all(item["kind"] == "agent" for item in body["items"])


async def test_list_items_search_filter(client, seeded):
    r = await client.get("/v1/items", params={"q": "next"})
    body = r.json()
    slugs = {item["slug"] for item in body["items"]}
    assert "nextjs-16" in slugs
    assert "tesslate-agent" not in slugs


async def test_item_detail_includes_versions(client, seeded):
    r = await client.get("/v1/items/agent/tesslate-agent")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "tesslate-agent"
    assert len(body["versions"]) >= 1
    assert body["versions"][0]["version"] == "0.1.0"
    assert body["pricing"]["pricing_type"] == "free"


async def test_item_detail_404(client, seeded):
    r = await client.get("/v1/items/agent/does-not-exist")
    assert r.status_code == 404
    body = r.json()
    assert body["detail"]["error"] == "item_not_found"


async def test_versions_list(client, seeded):
    r = await client.get("/v1/items/agent/tesslate-agent/versions")
    assert r.status_code == 200
    versions = r.json()
    assert any(v["version"] == "0.1.0" for v in versions)


async def test_categories(client, seeded):
    r = await client.get("/v1/categories", params={"kind": "agent"})
    assert r.status_code == 200
    body = r.json()
    slugs = {c["slug"] for c in body["categories"]}
    # Categories were seeded from item.category
    assert "fullstack" in slugs


async def test_featured(client, seeded):
    r = await client.get("/v1/featured", params={"kind": "agent"})
    assert r.status_code == 200
    body = r.json()
    slugs = {entry["item"]["slug"] for entry in body["featured"]}
    assert "tesslate-agent" in slugs
