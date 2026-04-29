"""Publish lifecycle — submission with bundle creates item + version."""

from __future__ import annotations

import base64
import json

from app.services.install_check import write_tar_zst


def _bundle_for(slug: str) -> str:
    payload = json.dumps({"slug": slug, "name": slug}).encode("utf-8")
    data = write_tar_zst({"item.manifest.json": payload})
    return base64.b64encode(data).decode("ascii")


async def test_publish_creates_item(client, env, auth_headers):
    payload = {
        "item": {
            "slug": "newcomer",
            "name": "Newcomer Agent",
            "description": "Brand new",
            "category": "fullstack",
            "tags": ["new"],
            "pricing": {"pricing_type": "free", "price_cents": 0, "currency": "usd"},
        },
        "version": {
            "version": "0.1.0",
            "changelog": "first release",
            "manifest": {"slug": "newcomer"},
            "bundle_b64": _bundle_for("newcomer"),
        },
    }
    res = await client.post("/v1/publish/agent", json=payload, headers=auth_headers)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["state"] == "approved"
    assert body["bundle_sha256"]
    stages = {c["stage"] for c in body["checks"]}
    assert stages == {"stage0", "stage1", "stage2", "stage3"}

    detail = await client.get("/v1/items/agent/newcomer")
    assert detail.status_code == 200
    assert detail.json()["versions"][0]["version"] == "0.1.0"


async def test_publish_rejects_invalid_slug(client, env, auth_headers):
    payload = {
        "item": {
            "slug": "bad slug!",
            "name": "Invalid",
            "pricing": {"pricing_type": "free", "price_cents": 0, "currency": "usd"},
        },
        "version": {"version": "0.1.0"},
    }
    res = await client.post("/v1/publish/agent", json=payload, headers=auth_headers)
    assert res.status_code == 201
    body = res.json()
    assert body["state"] == "rejected"
    assert any(c["status"] == "failed" for c in body["checks"])


async def test_submission_withdrawal(client, env, auth_headers):
    payload = {
        "item": {
            "slug": "withdrawer",
            "name": "Withdraw Me",
            "pricing": {"pricing_type": "free"},
        },
        "version": {"version": "0.1.0"},
    }
    res = await client.post("/v1/publish/agent", json=payload, headers=auth_headers)
    sub_id = res.json()["id"]
    # Approved submission cannot be withdrawn — use a rejected one instead.
    bad = await client.post(
        "/v1/publish/agent",
        json={"item": {"slug": "BAD", "name": "x"}, "version": {"version": "0.1.0"}},
        headers=auth_headers,
    )
    assert bad.json()["state"] == "rejected"
    # Confirm we cannot withdraw a terminal submission.
    fail = await client.post(f"/v1/submissions/{sub_id}/withdraw", headers=auth_headers)
    assert fail.status_code == 409
