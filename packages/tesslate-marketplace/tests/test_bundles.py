"""Bundle envelope shape, sha256 verification, signed URL round-trip."""

from __future__ import annotations

import hashlib


async def test_bundle_envelope_shape(client, seeded):
    r = await client.get("/v1/items/agent/tesslate-agent/versions/0.1.0/bundle")
    assert r.status_code == 200, r.text
    envelope = r.json()
    assert envelope["sha256"]
    assert envelope["size_bytes"] > 0
    assert envelope["content_type"] == "application/zstd"
    assert envelope["archive_format"] == "tar.zst"
    assert envelope["url"].startswith("http://testserver/v1/bundles/agent/tesslate-agent/0.1.0?")
    assert envelope["attestation"]["algorithm"] == "ed25519"


async def test_bundle_signed_url_streams_back(client, seeded):
    envelope = (await client.get("/v1/items/agent/tesslate-agent/versions/0.1.0/bundle")).json()
    # Strip the host so we hit the in-memory ASGI transport
    url = envelope["url"].replace("http://testserver", "")
    r = await client.get(url)
    assert r.status_code == 200
    assert r.headers["X-Tesslate-Bundle-Sha256"] == envelope["sha256"]
    assert hashlib.sha256(r.content).hexdigest() == envelope["sha256"]
    assert len(r.content) == envelope["size_bytes"]


async def test_bundle_signed_url_rejects_tampered_signature(client, seeded):
    envelope = (await client.get("/v1/items/agent/tesslate-agent/versions/0.1.0/bundle")).json()
    url = envelope["url"].replace("http://testserver", "")
    # Flip the last char of the signature
    tampered = url[:-1] + ("A" if url[-1] != "A" else "B")
    r = await client.get(tampered)
    assert r.status_code == 403


async def test_bundle_yank_returns_410(client, seeded, auth_headers):
    yank = await client.post(
        "/v1/yanks",
        json={"kind": "agent", "slug": "tesslate-agent", "version": "0.1.0", "reason": "broken", "severity": "medium"},
        headers=auth_headers,
    )
    assert yank.status_code == 201
    r = await client.get("/v1/items/agent/tesslate-agent/versions/0.1.0/bundle")
    assert r.status_code == 410
