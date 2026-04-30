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


# ---------------------------------------------------------------------------
# Cover every documented op in the 6-op vocabulary:
#   upsert, delete, deactivate, yank, version_remove, pricing_change.
# Each test mutates state via the corresponding handler and asserts the
# matching event appears in /v1/changes since the pre-mutation cursor.
# ---------------------------------------------------------------------------


async def _events_since(client, cursor: str) -> list[dict]:
    r = await client.get("/v1/changes", params={"since": cursor, "limit": 200})
    assert r.status_code == 200, r.text
    return r.json()["events"]


async def test_changes_op_upsert_emitted_on_publish(client, seeded, auth_headers):
    cursor = (await client.get("/v1/changes", params={"since": ""})).json()["next_etag"]
    res = await client.post(
        "/v1/publish/agent",
        json={
            "item": {"slug": "freshly-published", "name": "Fresh"},
            "version": {"version": "0.1.0"},
        },
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    events = await _events_since(client, cursor)
    matches = [e for e in events if e["op"] == "upsert" and e["slug"] == "freshly-published"]
    assert matches, events


async def test_changes_op_deactivate_emitted_on_item_level_yank(client, seeded, auth_headers):
    cursor = (await client.get("/v1/changes", params={"since": ""})).json()["next_etag"]
    res = await client.post(
        "/v1/yanks",
        json={
            "kind": "agent",
            "slug": "agent-builder",
            "reason": "obsolete",
            "severity": "medium",
        },
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    events = await _events_since(client, cursor)
    deactivates = [e for e in events if e["op"] == "deactivate" and e["slug"] == "agent-builder"]
    assert deactivates, events
    yanks = [e for e in events if e["op"] == "yank" and e["slug"] == "agent-builder"]
    assert yanks, events


async def test_changes_op_yank_emitted_on_version_yank(client, seeded, auth_headers):
    cursor = (await client.get("/v1/changes", params={"since": ""})).json()["next_etag"]
    res = await client.post(
        "/v1/yanks",
        json={
            "kind": "agent",
            "slug": "tesslate-agent",
            "version": "0.1.0",
            "reason": "regression",
            "severity": "medium",
        },
        headers=auth_headers,
    )
    assert res.status_code == 201
    events = await _events_since(client, cursor)
    assert any(e["op"] == "yank" and e["slug"] == "tesslate-agent" for e in events), events


async def test_changes_op_version_remove_emitted(client, seeded, auth_headers):
    # Add a second version so we can remove one without tripping the
    # only-version guard.
    await client.post(
        "/v1/publish/agent/tesslate-agent/versions/0.2.0",
        json={
            "item": {"slug": "tesslate-agent", "name": "Tesslate Agent"},
            "version": {"version": "0.2.0"},
        },
        headers=auth_headers,
    )
    cursor = (await client.get("/v1/changes", params={"since": ""})).json()["next_etag"]
    res = await client.delete(
        "/v1/items/agent/tesslate-agent/versions/0.1.0", headers=auth_headers
    )
    assert res.status_code == 204, res.text
    events = await _events_since(client, cursor)
    assert any(
        e["op"] == "version_remove" and e["slug"] == "tesslate-agent" and e["version"] == "0.1.0"
        for e in events
    ), events


async def test_changes_op_pricing_change_emitted(client, seeded, auth_headers):
    cursor = (await client.get("/v1/changes", params={"since": ""})).json()["next_etag"]
    res = await client.patch(
        "/v1/items/agent/paid-agent/pricing",
        json={"pricing_type": "free"},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    events = await _events_since(client, cursor)
    matches = [e for e in events if e["op"] == "pricing_change" and e["slug"] == "paid-agent"]
    assert matches, events
    payload = matches[-1]["payload"]
    assert payload["from"]["pricing_type"] == "paid"
    assert payload["to"]["pricing_type"] == "free"


async def test_changes_op_delete_emitted(client, seeded, auth_headers):
    cursor = (await client.get("/v1/changes", params={"since": ""})).json()["next_etag"]
    res = await client.delete("/v1/items/agent/agent-builder", headers=auth_headers)
    assert res.status_code == 204, res.text
    events = await _events_since(client, cursor)
    assert any(e["op"] == "delete" and e["slug"] == "agent-builder" for e in events), events
    # The row really is gone now.
    after = await client.get("/v1/items/agent/agent-builder")
    assert after.status_code == 404


async def test_pricing_change_no_op_does_not_emit(client, seeded, auth_headers):
    """PATCH that doesn't actually change anything must not pollute the feed."""
    cursor = (await client.get("/v1/changes", params={"since": ""})).json()["next_etag"]
    res = await client.patch(
        "/v1/items/agent/paid-agent/pricing",
        json={},
        headers=auth_headers,
    )
    assert res.status_code == 200
    events = await _events_since(client, cursor)
    assert not any(e["op"] == "pricing_change" for e in events)


async def test_version_remove_refuses_when_only_version(client, seeded, auth_headers):
    res = await client.delete(
        "/v1/items/agent/tesslate-agent/versions/0.1.0", headers=auth_headers
    )
    assert res.status_code == 409
    assert res.json()["detail"]["error"] == "cannot_remove_only_version"
