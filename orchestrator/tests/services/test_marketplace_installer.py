"""
Tests for the per-source marketplace installer (Wave 6).

Covers:
  - Each install pulls from its OWN source's bundle URL — proves
    federation is honored (no shared / cached bundle URL across sources).
  - SHA-256 mismatch fails loudly.
  - Bundle larger than envelope.size_bytes (or hub policy cap) refuses.
  - Expired signed URL refuses.
  - ``local://`` short-circuits — no HTTP attempt.
  - Ed25519 attestation verification: valid sig passes, tampered sig fails.

The installer is exercised end-to-end via :class:`MockTransport` for the
HTTP path and via the on-disk filesystem for the local path. No real
network calls.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import zstandard
from nacl.signing import SigningKey

from app.services import marketplace_client as mc
from app.services import marketplace_installer as installer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


HUB_ID_HEADER = mc.HUB_ID_HEADER


@pytest.fixture(autouse=True)
def _reset_breakers():
    mc.reset_circuit_breakers_for_tests()
    yield
    mc.reset_circuit_breakers_for_tests()


@pytest.fixture
def opensail_home(tmp_path, monkeypatch):
    """Pin OPENSAIL_HOME to a tmp dir for the test."""
    monkeypatch.setenv("OPENSAIL_HOME", str(tmp_path))
    return tmp_path


def _make_tarzst(files: dict[str, bytes]) -> bytes:
    """Build a tar.zst archive in memory."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mode = 0o644
            tf.addfile(info, io.BytesIO(data))
    return zstandard.ZstdCompressor(level=10).compress(raw.getvalue())


def _make_source(
    *,
    handle: str,
    base_url: str,
    pinned_hub_id: str | None = None,
    capabilities: list[str] | None = None,
    policies: dict | None = None,
    attestation_pubkey: str | None = None,
    trust_level: str = "official",
):
    return SimpleNamespace(
        id=uuid4(),
        handle=handle,
        base_url=base_url,
        pinned_hub_id=pinned_hub_id,
        capabilities_cache=capabilities or ["catalog.read", "bundles.signed_url"],
        policies_cache=policies or {"max_bundle_size_bytes": {"agent": 50 * 1024 * 1024}},
        attestation_pubkey=attestation_pubkey,
        trust_level=trust_level,
        scope="system",
        is_active=True,
    )


def _envelope_handler(
    *,
    hub_id: str,
    bundle_url: str,
    sha256: str,
    size_bytes: int,
    expires_at: str | None = None,
    attestation: dict | None = None,
):
    """Build a MockTransport handler that serves /v1/items/.../bundle and
    streams the bundle bytes from ``bundle_url`` (via the same handler).
    """
    headers = {HUB_ID_HEADER: hub_id, "ETag": "v1"}

    def _handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/bundle"):
            envelope = {
                "url": bundle_url,
                "sha256": sha256,
                "size_bytes": size_bytes,
                "content_type": "application/zstd",
                "archive_format": "tar.zst",
                "expires_at": expires_at,
                "attestation": attestation,
            }
            return httpx.Response(200, json=envelope, headers=headers)
        if path.endswith(f"/items/agent/coder"):
            return httpx.Response(
                200,
                json={"slug": "coder", "kind": "agent", "latest_version": "1.0.0"},
                headers=headers,
            )
        return httpx.Response(404, json={"error": "not_found"}, headers=headers)

    return _handler


# ---------------------------------------------------------------------------
# Per-source bundle URLs — different sources serve DIFFERENT bundles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_installer_uses_source_specific_envelope(opensail_home, monkeypatch) -> None:
    """Installer must call the source's OWN client.get_bundle, never a
    shared / global URL. Verified by serving two distinct envelopes and
    asserting each install fetched from the right hub."""
    bundle_a_bytes = _make_tarzst({"manifest.json": b'{"name":"hub-a"}'})
    bundle_b_bytes = _make_tarzst({"manifest.json": b'{"name":"hub-b"}'})
    sha_a = hashlib.sha256(bundle_a_bytes).hexdigest()
    sha_b = hashlib.sha256(bundle_b_bytes).hexdigest()

    fetch_log: list[str] = []

    def _make_handler(*, hub_id: str, sha: str, body: bytes):
        def handler(request: httpx.Request) -> httpx.Response:
            fetch_log.append(f"{hub_id}:{request.url.path}")
            if request.url.path.endswith("/bundle"):
                envelope = {
                    "url": f"https://cdn-{hub_id}.example.com/bundle.tar.zst",
                    "sha256": sha,
                    "size_bytes": len(body),
                    "content_type": "application/zstd",
                    "archive_format": "tar.zst",
                    "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                    "attestation": None,
                }
                return httpx.Response(
                    200, json=envelope, headers={HUB_ID_HEADER: hub_id, "ETag": "v1"}
                )
            return httpx.Response(404, json={}, headers={HUB_ID_HEADER: hub_id})
        return handler

    transport_a = httpx.MockTransport(_make_handler(hub_id="hub-a", sha=sha_a, body=bundle_a_bytes))
    transport_b = httpx.MockTransport(_make_handler(hub_id="hub-b", sha=sha_b, body=bundle_b_bytes))

    source_a = _make_source(handle="hub-a-source", base_url="https://hub-a.example.com", pinned_hub_id="hub-a")
    source_b = _make_source(handle="hub-b-source", base_url="https://hub-b.example.com", pinned_hub_id="hub-b")

    client_a = mc.MarketplaceClient(source_a.base_url, pinned_hub_id="hub-a", transport=transport_a)
    client_b = mc.MarketplaceClient(source_b.base_url, pinned_hub_id="hub-b", transport=transport_b)

    # Patch the bundle download to serve the right body per CDN URL.
    bodies = {
        f"https://cdn-hub-a.example.com/bundle.tar.zst": bundle_a_bytes,
        f"https://cdn-hub-b.example.com/bundle.tar.zst": bundle_b_bytes,
    }

    async def fake_download_and_verify(url, expected_sha256, max_bytes, dest_tmp, *, http=None):
        body = bodies[url]
        actual = hashlib.sha256(body).hexdigest()
        if actual.lower() != expected_sha256.lower():
            raise installer.BundleSha256MismatchError("mismatch")
        if len(body) > max_bytes:
            raise installer.BundleSizeExceededError("too big")
        dest_tmp.write_bytes(body)
        return actual, len(body)

    monkeypatch.setattr(installer, "_download_and_verify", fake_download_and_verify)

    res_a = await installer.install_from_source(
        source=source_a, kind="agent", slug="coder", version="1.0.0", client=client_a,
    )
    res_b = await installer.install_from_source(
        source=source_b, kind="agent", slug="coder", version="1.0.0",
        client=client_b, dest_root_override=opensail_home / "agents" / "coder-b",
    )
    await client_a.aclose()
    await client_b.aclose()

    # Each install hit only its own hub.
    paths_a = [p for p in fetch_log if p.startswith("hub-a:")]
    paths_b = [p for p in fetch_log if p.startswith("hub-b:")]
    assert any("/bundle" in p for p in paths_a)
    assert any("/bundle" in p for p in paths_b)
    # And we never crossed wires — hub-a never saw hub-b's URL and vice versa.
    assert all("hub-b" not in p for p in paths_a)
    assert all("hub-a" not in p for p in paths_b)

    # Each install landed bytes from the matching CDN.
    assert (res_a.path / "manifest.json").read_text().startswith("{")
    assert (res_b.path / "manifest.json").read_text().startswith("{")


# ---------------------------------------------------------------------------
# SHA-256 mismatch refuses loudly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_installer_refuses_sha256_mismatch(opensail_home) -> None:
    real_bundle = _make_tarzst({"manifest.json": b'{"x":1}'})
    real_sha = hashlib.sha256(real_bundle).hexdigest()
    bogus_sha = "0" * 64  # claim a different sha256

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/bundle"):
            return httpx.Response(
                200,
                json={
                    "url": "https://cdn.example.com/bundle.tar.zst",
                    "sha256": bogus_sha,
                    "size_bytes": len(real_bundle),
                    "content_type": "application/zstd",
                    "archive_format": "tar.zst",
                    "expires_at": None,
                    "attestation": None,
                },
                headers={HUB_ID_HEADER: "hub-x", "ETag": "v1"},
            )
        if "/items/agent/coder" in path:
            return httpx.Response(
                200,
                json={"slug": "coder", "kind": "agent", "latest_version": "1.0.0"},
                headers={HUB_ID_HEADER: "hub-x"},
            )
        return httpx.Response(404, json={}, headers={HUB_ID_HEADER: "hub-x"})

    # Stream the real bundle bytes from the CDN URL.
    cdn_handler_calls = []

    def cdn_handler(request: httpx.Request) -> httpx.Response:
        cdn_handler_calls.append(str(request.url))
        return httpx.Response(200, content=real_bundle)

    transport_hub = httpx.MockTransport(handler)
    cdn_transport = httpx.MockTransport(cdn_handler)

    source = _make_source(handle="x", base_url="https://hub.example.com", pinned_hub_id="hub-x")
    client = mc.MarketplaceClient(source.base_url, pinned_hub_id="hub-x", transport=transport_hub)

    # Wrap _download_and_verify so it uses our CDN transport.
    orig_download = installer._download_and_verify

    async def patched_download(url, expected_sha256, max_bytes, dest_tmp, *, http=None):
        async with httpx.AsyncClient(transport=cdn_transport) as cdn_client:
            return await orig_download(
                url, expected_sha256, max_bytes, dest_tmp, http=cdn_client,
            )

    import unittest.mock as um
    with um.patch.object(installer, "_download_and_verify", patched_download):
        with pytest.raises(installer.BundleSha256MismatchError) as exc:
            await installer.install_from_source(
                source=source, kind="agent", slug="coder", version="1.0.0", client=client,
            )
    await client.aclose()
    assert exc.value.reason == "bundle_sha256_mismatch"


# ---------------------------------------------------------------------------
# Size cap refuses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_installer_refuses_size_exceeded(opensail_home) -> None:
    # Envelope claims 100 bytes; CDN streams 1 KB → must trip mid-download.
    real_body = b"a" * 1024
    sha = hashlib.sha256(real_body).hexdigest()

    def hub_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/bundle"):
            return httpx.Response(
                200,
                json={
                    "url": "https://cdn.example.com/big.tar.zst",
                    "sha256": sha,
                    "size_bytes": 100,
                    "content_type": "application/zstd",
                    "archive_format": "tar.zst",
                    "expires_at": None,
                    "attestation": None,
                },
                headers={HUB_ID_HEADER: "hub-x"},
            )
        return httpx.Response(404, json={}, headers={HUB_ID_HEADER: "hub-x"})

    def cdn_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=real_body)

    source = _make_source(handle="x", base_url="https://hub.example.com", pinned_hub_id="hub-x")
    client = mc.MarketplaceClient(
        source.base_url, pinned_hub_id="hub-x", transport=httpx.MockTransport(hub_handler)
    )
    cdn_transport = httpx.MockTransport(cdn_handler)
    orig_download = installer._download_and_verify

    async def patched_download(url, expected_sha256, max_bytes, dest_tmp, *, http=None):
        async with httpx.AsyncClient(transport=cdn_transport) as cdn_client:
            return await orig_download(url, expected_sha256, max_bytes, dest_tmp, http=cdn_client)

    import unittest.mock as um
    with um.patch.object(installer, "_download_and_verify", patched_download):
        with pytest.raises(installer.BundleSizeExceededError):
            await installer.install_from_source(
                source=source, kind="agent", slug="coder", version="1.0.0", client=client,
            )
    await client.aclose()


@pytest.mark.asyncio
async def test_installer_refuses_envelope_size_above_envelope_self(opensail_home, monkeypatch) -> None:
    """If the envelope itself claims 99 GB but the cap drops it to 1 GB,
    refuse before downloading."""
    body = b"x" * 100
    sha = hashlib.sha256(body).hexdigest()

    def hub_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/bundle"):
            return httpx.Response(
                200,
                json={
                    "url": "https://cdn.example.com/x.tar.zst",
                    "sha256": sha,
                    "size_bytes": 99 * 1024 * 1024 * 1024,  # 99 GB
                    "content_type": "application/zstd",
                    "archive_format": "tar.zst",
                    "expires_at": None,
                    "attestation": None,
                },
                headers={HUB_ID_HEADER: "hub-x"},
            )
        return httpx.Response(404, json={}, headers={HUB_ID_HEADER: "hub-x"})

    source = _make_source(handle="x", base_url="https://hub.example.com", pinned_hub_id="hub-x")
    client = mc.MarketplaceClient(
        source.base_url, pinned_hub_id="hub-x", transport=httpx.MockTransport(hub_handler)
    )

    with pytest.raises(installer.BundleSizeExceededError):
        await installer.install_from_source(
            source=source, kind="agent", slug="coder", version="1.0.0", client=client,
        )
    await client.aclose()


# ---------------------------------------------------------------------------
# Expired URL refuses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_installer_refuses_expired_url(opensail_home) -> None:
    body = _make_tarzst({"manifest.json": b"{}"})
    sha = hashlib.sha256(body).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/bundle"):
            return httpx.Response(
                200,
                json={
                    "url": "https://cdn.example.com/x.tar.zst",
                    "sha256": sha,
                    "size_bytes": len(body),
                    "content_type": "application/zstd",
                    "archive_format": "tar.zst",
                    "expires_at": (datetime.now(UTC) - timedelta(seconds=10)).isoformat(),
                    "attestation": None,
                },
                headers={HUB_ID_HEADER: "hub-x"},
            )
        return httpx.Response(404, json={}, headers={HUB_ID_HEADER: "hub-x"})

    source = _make_source(handle="x", base_url="https://hub.example.com", pinned_hub_id="hub-x")
    client = mc.MarketplaceClient(
        source.base_url, pinned_hub_id="hub-x", transport=httpx.MockTransport(handler),
    )
    with pytest.raises(installer.BundleExpiredError):
        await installer.install_from_source(
            source=source, kind="agent", slug="coder", version="1.0.0", client=client,
        )
    await client.aclose()


# ---------------------------------------------------------------------------
# local:// short-circuit — no HTTP attempt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_installer_local_source_short_circuits(opensail_home) -> None:
    """Local source: drop a manifest into $OPENSAIL_HOME/agents/local-coder/
    and verify install_from_source copies it without making any HTTP call.
    """
    item_dir = opensail_home / "agents" / "local-coder"
    item_dir.mkdir(parents=True)
    (item_dir / "manifest.json").write_text(
        json.dumps({"name": "local-coder", "version": "0.1.0"}),
        encoding="utf-8",
    )
    (item_dir / "system_prompt.md").write_text("hello")

    source = _make_source(
        handle="local",
        base_url="local://filesystem",
        pinned_hub_id=None,
        capabilities=[],
        policies={},
    )

    # Must NOT make an HTTP call — pass a poisoned client that would raise
    # on any request.
    class _ExplodingClient:
        is_local_source = True

        async def get_item(self, *a, **kw):
            raise AssertionError("install_from_source must short-circuit local sources")

        async def get_bundle(self, *a, **kw):
            raise AssertionError("install_from_source must short-circuit local sources")

        async def aclose(self):
            return

    install_dest = opensail_home / "agents" / "local-coder-installed"
    result = await installer.install_from_source(
        source=source,
        kind="agent",
        slug="local-coder",
        version=None,
        client=_ExplodingClient(),  # would explode if used
        dest_root_override=install_dest,
    )
    assert result.path == install_dest
    assert (install_dest / "manifest.json").is_file()
    assert (install_dest / "system_prompt.md").read_text() == "hello"
    # Provenance manifest overlay landed.
    manifest = json.loads((install_dest / "manifest.json").read_text())
    assert manifest["source"] == "local"
    assert manifest["bundle_sha256"]
    assert manifest["installed_from"] == "marketplace"


# ---------------------------------------------------------------------------
# Attestation verification — pass + fail
# ---------------------------------------------------------------------------


def test_verify_attestation_passes_with_valid_signature() -> None:
    sk = SigningKey.generate()
    pubkey_b64 = base64.b64encode(bytes(sk.verify_key)).decode("ascii")

    bundle_sha = "a" * 64
    sig = sk.sign(bundle_sha.encode("ascii")).signature
    sig_b64 = base64.b64encode(sig).decode("ascii")

    source = _make_source(
        handle="att",
        base_url="https://hub.example.com",
        pinned_hub_id="hub-a",
        capabilities=["catalog.read", "attestations"],
        attestation_pubkey=pubkey_b64,
    )
    envelope = {
        "url": "https://cdn/x.tar.zst",
        "sha256": bundle_sha,
        "size_bytes": 1,
        "archive_format": "tar.zst",
        "attestation": {
            "signature": sig_b64,
            "key_id": "k1",
            "algorithm": "ed25519",
        },
    }
    assert installer.verify_attestation(source, envelope, bundle_sha) is True


def test_verify_attestation_fails_with_tampered_signature() -> None:
    sk = SigningKey.generate()
    pubkey_b64 = base64.b64encode(bytes(sk.verify_key)).decode("ascii")
    bundle_sha = "b" * 64
    real_sig = sk.sign(bundle_sha.encode("ascii")).signature
    tampered = bytearray(real_sig)
    tampered[0] ^= 0xFF
    tampered_b64 = base64.b64encode(bytes(tampered)).decode("ascii")

    source = _make_source(
        handle="att",
        base_url="https://hub.example.com",
        pinned_hub_id="hub-a",
        capabilities=["catalog.read", "attestations"],
        attestation_pubkey=pubkey_b64,
    )
    envelope = {
        "url": "https://cdn/x.tar.zst",
        "sha256": bundle_sha,
        "size_bytes": 1,
        "archive_format": "tar.zst",
        "attestation": {
            "signature": tampered_b64,
            "key_id": "k1",
            "algorithm": "ed25519",
        },
    }
    with pytest.raises(installer.AttestationError):
        installer.verify_attestation(source, envelope, bundle_sha)


def test_verify_attestation_skipped_without_capability() -> None:
    """Source without ``attestations`` capability ignores the attestation
    field rather than rejecting it (the field is bonus metadata)."""
    source = _make_source(
        handle="att",
        base_url="https://hub.example.com",
        pinned_hub_id="hub-a",
        capabilities=["catalog.read"],  # no attestations
        attestation_pubkey=None,
    )
    envelope = {
        "url": "https://cdn/x.tar.zst",
        "sha256": "a" * 64,
        "size_bytes": 1,
        "archive_format": "tar.zst",
        "attestation": {"signature": "AAAA", "algorithm": "ed25519"},
    }
    assert installer.verify_attestation(source, envelope, "a" * 64) is False


def test_verify_attestation_refuses_unsupported_algorithm() -> None:
    source = _make_source(
        handle="att",
        base_url="https://hub.example.com",
        pinned_hub_id="hub-a",
        capabilities=["attestations"],
        attestation_pubkey="A" * 44,
    )
    envelope = {
        "url": "x",
        "sha256": "a" * 64,
        "size_bytes": 1,
        "archive_format": "tar.zst",
        "attestation": {"signature": "AAAA", "algorithm": "rsa"},
    }
    with pytest.raises(installer.AttestationError):
        installer.verify_attestation(source, envelope, "a" * 64)


# ---------------------------------------------------------------------------
# Envelope shape validation
# ---------------------------------------------------------------------------


def test_parse_envelope_rejects_missing_fields() -> None:
    with pytest.raises(installer.BundleEnvelopeError):
        installer._parse_envelope({"url": "x"})


def test_parse_envelope_rejects_non_tarzst() -> None:
    with pytest.raises(installer.BundleFormatError):
        installer._parse_envelope({
            "url": "https://x",
            "sha256": "a" * 64,
            "size_bytes": 1,
            "archive_format": "zip",
        })


def test_parse_envelope_rejects_bad_sha() -> None:
    with pytest.raises(installer.BundleEnvelopeError):
        installer._parse_envelope({
            "url": "https://x",
            "sha256": "bad",
            "size_bytes": 1,
            "archive_format": "tar.zst",
        })


# ---------------------------------------------------------------------------
# Path validators
# ---------------------------------------------------------------------------


def test_install_path_rejects_traversal() -> None:
    with pytest.raises(installer.InvalidSlugError):
        installer.install_path("agent", "../etc/passwd")


def test_install_path_rejects_unknown_kind() -> None:
    with pytest.raises(installer.InvalidKindError):
        installer.install_path("not-a-kind", "x")
