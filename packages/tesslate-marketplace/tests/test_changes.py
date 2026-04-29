"""Changes feed ordering, etag pagination, tombstones."""

from __future__ import annotations


async def test_changes_seed_events(client, seeded):
    r = await client.get("/v1/changes", params={"since": ""})
    assert r.status_code == 200
    body = r.json()
    assert body["events"]
    ops = {e["op"] for e in body["events"]}
    assert "upsert" in ops
    # next_etag corresponds to the last event when has_more=False
    assert body["next_etag"].startswith("v")


async def test_changes_pagination(client, seeded):
    first = await client.get("/v1/changes", params={"since": "", "limit": 2})
    body = first.json()
    assert len(body["events"]) <= 2
    if body["has_more"]:
        next_page = await client.get("/v1/changes", params={"since": body["next_etag"]})
        assert next_page.status_code == 200


async def test_changes_yank_emits_tombstone(client, seeded, auth_headers):
    snap = (await client.get("/v1/changes", params={"since": ""})).json()
    cursor = snap["next_etag"]
    res = await client.post(
        "/v1/yanks",
        json={"kind": "agent", "slug": "tesslate-agent", "version": "0.1.0", "reason": "broken", "severity": "medium"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    delta = await client.get("/v1/changes", params={"since": cursor})
    body = delta.json()
    assert any(e["op"] == "yank" for e in body["events"])


async def test_yanks_feed_filters_to_yank_ops(client, seeded, auth_headers):
    await client.post(
        "/v1/yanks",
        json={"kind": "agent", "slug": "tesslate-agent", "version": "0.1.0", "reason": "broken", "severity": "medium"},
        headers=auth_headers,
    )
    feed = await client.get("/v1/yanks", params={"since": ""})
    assert feed.status_code == 200
    body = feed.json()
    assert body["events"]
    assert all(e["op"] in ("yank", "version_remove") for e in body["events"])
