"""Reviews — read list, read aggregate, write per-user single review."""

from __future__ import annotations


async def test_list_reviews_returns_seeded(client, seeded):
    r = await client.get("/v1/items/agent/tesslate-agent/reviews")
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(rv["reviewer_handle"] == "user-a" for rv in body["reviews"])


async def test_review_aggregate_reflects_seeds(client, seeded):
    r = await client.get("/v1/items/agent/tesslate-agent/reviews/aggregate")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert body["mean"] > 0


async def test_create_review_returns_201_then_update_returns_200(client, seeded, auth_headers):
    """Per-user single review: first POST creates (201), second updates (200)."""
    payload = {
        "rating": 4,
        "title": "Good",
        "body": "Works well",
        "reviewer_handle": "user-double",
    }
    first = await client.post(
        "/v1/items/agent/agent-builder/reviews", json=payload, headers=auth_headers
    )
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]

    # Re-post by the same handle — must update in place, not insert.
    payload_update = {
        "rating": 2,
        "title": "Changed my mind",
        "body": "Found a bug",
        "reviewer_handle": "user-double",
    }
    second = await client.post(
        "/v1/items/agent/agent-builder/reviews", json=payload_update, headers=auth_headers
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["id"] == first_id
    assert second_body["rating"] == 2
    assert second_body["title"] == "Changed my mind"

    # Aggregate must show count==1, not 2.
    agg = await client.get("/v1/items/agent/agent-builder/reviews/aggregate")
    body = agg.json()
    assert body["count"] == 1
    assert body["mean"] == 2.0

    listing = await client.get("/v1/items/agent/agent-builder/reviews")
    matches = [r for r in listing.json()["reviews"] if r["reviewer_handle"] == "user-double"]
    assert len(matches) == 1


async def test_create_review_distinct_handles_create_separate_rows(client, seeded, auth_headers):
    for i, handle in enumerate(["user-x", "user-y", "user-z"]):
        r = await client.post(
            "/v1/items/agent/agent-builder/reviews",
            json={"rating": 5 - i, "reviewer_handle": handle},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text

    agg = await client.get("/v1/items/agent/agent-builder/reviews/aggregate")
    assert agg.json()["count"] == 3
