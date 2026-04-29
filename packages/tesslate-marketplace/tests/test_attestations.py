"""Detached signature verifies; tampered bundle fails."""

from __future__ import annotations


async def test_attestation_round_trip(client, seeded):
    envelope = (await client.get("/v1/items/agent/tesslate-agent/versions/0.1.0/bundle")).json()
    sha = envelope["sha256"]
    sig = envelope["attestation"]["signature"]

    from app.services.attestations import get_attestor

    attestor = get_attestor()
    assert attestor.verify_sha256(sha, sig)


async def test_attestation_endpoint(client, seeded):
    r = await client.get("/v1/items/agent/tesslate-agent/versions/0.1.0/attestation")
    assert r.status_code == 200
    body = r.json()
    assert body["algorithm"] == "ed25519"
    assert body["signature"]


async def test_attestation_rejects_tampered_sha(client, seeded):
    from app.services.attestations import get_attestor

    attestor = get_attestor()
    envelope = (await client.get("/v1/items/agent/tesslate-agent/versions/0.1.0/bundle")).json()
    tampered_sha = "0" * 64
    assert not attestor.verify_sha256(tampered_sha, envelope["attestation"]["signature"])
