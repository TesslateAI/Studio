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


async def test_items_cursor_pagination_complete_and_unique(client, env, auth_headers):
    """Paginate a fixed corpus with limit=2 and assert no repeats / no gaps.

    Regression for the broken `Item.id != after_id` cursor that returned the
    same set on every page minus one row. Uses a fresh, freshly-seeded skill
    catalog so the assertion is deterministic.
    """
    # Insert 5 items directly so we control timing and slugs.
    import asyncio

    from app.database import session_scope
    from app.models import Item

    async with session_scope() as session:
        for i in range(5):
            session.add(
                Item(
                    kind="skill",
                    slug=f"page-skill-{i:02d}",
                    name=f"Page Skill {i}",
                    description="cursor pagination corpus",
                    pricing_payload={"pricing_type": "free", "price_cents": 0, "currency": "usd"},
                )
            )
            await session.flush()
            # Distinct created_at per row so descending order is unambiguous.
            await asyncio.sleep(0.01)

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, str] = {"kind": "skill", "limit": "2", "sort": "newest"}
        if cursor:
            params["cursor"] = cursor
        r = await client.get("/v1/items", params=params)
        assert r.status_code == 200, r.text
        body = r.json()
        page_slugs = [it["slug"] for it in body["items"]]
        assert all(s not in seen for s in page_slugs), (
            f"page repeated already-seen slugs: page={page_slugs} seen={seen}"
        )
        seen.extend(page_slugs)
        pages += 1
        if not body["has_more"]:
            break
        cursor = body["next_cursor"]
        assert cursor, "has_more=true requires next_cursor"
        assert pages < 10, "pagination loop did not terminate"

    # All 5 corpus items must appear exactly once.
    corpus = {f"page-skill-{i:02d}" for i in range(5)}
    assert corpus.issubset(set(seen)), f"missing items from pagination: {corpus - set(seen)}"
