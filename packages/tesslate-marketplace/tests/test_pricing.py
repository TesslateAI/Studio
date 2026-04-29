"""Pricing read + dev-mode checkout."""

from __future__ import annotations


async def test_pricing_read(client, seeded):
    r = await client.get("/v1/items/agent/paid-agent/pricing")
    assert r.status_code == 200
    body = r.json()
    assert body["pricing"]["pricing_type"] == "paid"
    assert body["pricing"]["price_cents"] == 1500


async def test_checkout_dev_mode(client, seeded):
    r = await client.post(
        "/v1/items/agent/paid-agent/checkout",
        json={"customer_email": "user@example.com"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "dev_simulator"
    assert body["session_id"].startswith("dev_")
    assert "/dev/checkout/" in body["checkout_url"]

    # Dev landing should render
    landing = await client.get(f"/dev/checkout/{body['session_id']}")
    assert landing.status_code == 200
    assert "Dev checkout simulator" in landing.text


async def test_checkout_refuses_free_item(client, seeded):
    r = await client.post(
        "/v1/items/agent/tesslate-agent/checkout",
        json={"customer_email": "user@example.com"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "item_is_free"
