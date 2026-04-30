"""Yank emit + appeal flow; critical severity goes through two-admin gate."""

from __future__ import annotations


async def test_yank_emit_flips_version(client, seeded, auth_headers):
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
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["state"] == "resolved"

    detail = await client.get("/v1/items/agent/tesslate-agent/versions/0.1.0")
    assert detail.json()["is_yanked"] is True


async def test_yank_critical_requires_appeal(client, seeded, auth_headers, auth_headers_admin_2):
    yank = await client.post(
        "/v1/yanks",
        json={
            "kind": "agent",
            "slug": "tesslate-agent",
            "version": "0.1.0",
            "reason": "vuln",
            "severity": "critical",
        },
        headers=auth_headers,
    )
    assert yank.status_code == 201
    body = yank.json()
    assert body["state"] == "open"
    yid = body["id"]

    # The two-admin policy requires the appeal to come from a *different* admin
    # than the one who filed the critical yank.
    appeal = await client.post(
        f"/v1/yanks/{yid}/appeal",
        json={"reason": "second-admin confirms"},
        headers=auth_headers_admin_2,
    )
    assert appeal.status_code == 201, appeal.text

    final = await client.get(f"/v1/yanks/{yid}")
    assert final.json()["state"] == "resolved"


async def test_critical_yank_self_appeal_rejected(client, seeded, auth_headers):
    """The same admin who filed a critical yank cannot resolve their own appeal."""
    yank = await client.post(
        "/v1/yanks",
        json={
            "kind": "agent",
            "slug": "tesslate-agent",
            "version": "0.1.0",
            "reason": "vuln",
            "severity": "critical",
        },
        headers=auth_headers,
    )
    assert yank.status_code == 201
    yid = yank.json()["id"]

    appeal = await client.post(
        f"/v1/yanks/{yid}/appeal",
        json={"reason": "i confirm myself"},
        headers=auth_headers,
    )
    assert appeal.status_code == 409, appeal.text
    body = appeal.json()
    assert body["detail"]["error"] == "cannot_self_appeal_critical_yank"

    # The yank stays open until a real second admin confirms it.
    final = await client.get(f"/v1/yanks/{yid}")
    assert final.json()["state"] == "open"


async def test_yank_requires_auth(client, seeded):
    res = await client.post(
        "/v1/yanks",
        json={
            "kind": "agent",
            "slug": "tesslate-agent",
            "version": "0.1.0",
            "reason": "x",
            "severity": "low",
        },
    )
    assert res.status_code == 401
