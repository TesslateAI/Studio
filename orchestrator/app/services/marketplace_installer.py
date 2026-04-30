"""
Marketplace installer — per-source bundle resolution + safe extraction.

Wave 6 makes this the canonical install path for every marketplace item
(agent / skill / mcp_server / base / theme / workflow_template / app).
The legacy cloud-mediated path is preserved as a fallback for sources
that explicitly require it (paid items in Tesslate Official today).

Pipeline:
  1. Resolve the bundle envelope via the source's
     :class:`MarketplaceClient` (``get_bundle``) — the envelope is the
     spec-defined ``{url, sha256, size_bytes, content_type,
     archive_format, expires_at, attestation}`` shape.
  2. **Local short-circuit**: if ``source.base_url.startswith('local://')``
     bypass HTTP and call :mod:`marketplace_local` for the envelope and
     payload (still verifying sha256 for parity).
  3. **Pre-flight checks** on the envelope:
       - ``size_bytes`` ≤ source.policies_cache.max_bundle_size_bytes[kind]
         (when set) AND ≤ envelope.size_bytes (the envelope itself is a
         hub-side cap).
       - ``expires_at`` (if present) is in the future.
       - ``archive_format`` is exactly ``"tar.zst"``.
  4. **Download** to a tmp file with streaming sha256 verification AND
     a hard size cap. Refuse if either gate trips.
  5. **Attestation** (if envelope advertises one AND source advertises
     ``attestations`` AND the source has a pinned pubkey): verify the
     ed25519 signature over the bundle's sha256 before extraction. On
     first verification with no cached pubkey, capture the manifest's
     ``key_id``-keyed pubkey for future calls.
  6. **Extract** via :func:`install_extract.safe_extract` ONLY — no
     ``tarfile.extractall`` anywhere. ``$OPENSAIL_HOME/{kind}s/{slug}/``
     is the destination on desktop; the cloud installer overrides via
     ``dest_root_override``.
  7. Atomic rename ``staging/`` → ``{kind}s/{slug}/`` so a partial
     install can never appear.

Every failure surfaces as a typed :class:`InstallError` subclass with a
machine-readable ``reason`` so routers / UI can branch without
string-matching.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import httpx
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from . import marketplace_local
from .cloud_client import (
    CircuitOpenError,
    CloudClient,
    NotPairedError,
    get_cloud_client,
)
from .desktop_paths import resolve_opensail_home
from .install_extract import (
    ArchiveTooLargeError,
    UnsafeArchiveError,
    safe_extract,
)

logger = logging.getLogger(__name__)


_KIND_TO_DIR: Final[dict[str, str]] = {
    "agent": "agents",
    "skill": "skills",
    "mcp_server": "mcp_servers",
    "base": "bases",
    "theme": "themes",
    "workflow_template": "workflow_templates",
    "app": "apps",
}

_DOWNLOAD_TIMEOUT: Final[httpx.Timeout] = httpx.Timeout(60.0, connect=10.0)
_STREAM_CHUNK_BYTES: Final[int] = 64 * 1024

# Hard global ceiling — even if the source advertises a higher per-kind cap
# we refuse anything larger. This is a sanity backstop, NOT the primary cap.
_GLOBAL_HARD_CAP_BYTES: Final[int] = 1024 * 1024 * 1024  # 1 GB

# Default per-kind caps used when the source did not advertise its own
# ``policies.max_bundle_size_bytes`` (e.g. local sources, or a hub that
# omitted the field). Mirrors the protocol's per-kind constraints.
_DEFAULT_MAX_BUNDLE_BYTES: Final[dict[str, int]] = {
    "agent": 50 * 1024 * 1024,
    "skill": 10 * 1024 * 1024,
    "theme": 10 * 1024 * 1024,
    "workflow_template": 10 * 1024 * 1024,
    "mcp_server": 1 * 1024 * 1024,
    "base": 1 * 1024 * 1024,
    "app": 500 * 1024 * 1024,
}


# ---------------------------------------------------------------------------
# Typed errors — every refusal has a stable ``reason`` token.
# ---------------------------------------------------------------------------


class InstallError(Exception):
    """Base for every installer failure."""

    reason: str = "install_error"

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        if reason is not None:
            self.reason = reason
        self.message = message


class InvalidKindError(InstallError):
    reason = "invalid_kind"


class InvalidSlugError(InstallError):
    reason = "invalid_slug"


class AlreadyInstalledError(InstallError):
    reason = "already_installed"


class BundleEnvelopeError(InstallError):
    """The /v1 bundle envelope is malformed or missing required fields."""

    reason = "bundle_envelope_invalid"


class BundleExpiredError(InstallError):
    """The signed download URL has expired before we could fetch it."""

    reason = "bundle_expired"


class BundleSizeExceededError(InstallError):
    """Either the envelope or the actual download is over policy."""

    reason = "bundle_size_exceeded"


class BundleSha256MismatchError(InstallError):
    """The downloaded bytes hash to a different sha256 than the envelope."""

    reason = "bundle_sha256_mismatch"


class BundleFormatError(InstallError):
    """Envelope.archive_format is not tar.zst."""

    reason = "bundle_format_unsupported"


class AttestationError(InstallError):
    """Bundle attestation signature failed to verify."""

    reason = "attestation_invalid"


class CloudFallbackUnavailableError(InstallError):
    """The source requires cloud-mediation but the cloud is unreachable."""

    reason = "cloud_unavailable"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InstallResult:
    kind: str
    slug: str
    version: str
    path: Path
    sha256: str
    size_bytes: int
    source_handle: str
    install_id: str | None = None  # only set on cloud-mediated installs


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _validate_kind(kind: str) -> None:
    if kind not in _KIND_TO_DIR:
        raise InvalidKindError(f"unknown kind: {kind!r}")


def _validate_slug(slug: str) -> None:
    if not slug:
        raise InvalidSlugError("slug is empty")
    if "/" in slug or "\\" in slug or ".." in slug:
        raise InvalidSlugError(f"invalid slug: {slug!r}")
    if any(c in slug for c in ("\x00", ":")):
        raise InvalidSlugError(f"invalid slug characters: {slug!r}")


def _default_install_dir(kind: str, slug: str) -> Path:
    _validate_kind(kind)
    _validate_slug(slug)
    return resolve_opensail_home() / _KIND_TO_DIR[kind] / slug


def install_path(kind: str, slug: str) -> Path:
    """Public helper: resolve the on-disk path for ``{kind}/{slug}``.

    Used by routers to render install metadata + by uninstall.
    """
    return _default_install_dir(kind, slug)


# ---------------------------------------------------------------------------
# Envelope validation
# ---------------------------------------------------------------------------


def _parse_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Validate a /v1 bundle envelope and return a normalised copy.

    Refuses missing/wrong-typed required fields. ``expires_at`` and
    ``attestation`` are optional.
    """
    if not isinstance(envelope, dict):
        raise BundleEnvelopeError("envelope is not a JSON object")
    url = envelope.get("url")
    sha256 = envelope.get("sha256")
    size_bytes = envelope.get("size_bytes")
    archive_format = envelope.get("archive_format")
    if not isinstance(url, str) or not url:
        raise BundleEnvelopeError("envelope.url missing or not a string")
    if (
        not isinstance(sha256, str)
        or len(sha256) != 64
        or not all(c in "0123456789abcdefABCDEF" for c in sha256)
    ):
        raise BundleEnvelopeError("envelope.sha256 missing or malformed")
    if not isinstance(size_bytes, int) or size_bytes < 0:
        raise BundleEnvelopeError("envelope.size_bytes missing or invalid")
    if not isinstance(archive_format, str):
        raise BundleEnvelopeError("envelope.archive_format missing")
    if archive_format != "tar.zst":
        raise BundleFormatError(
            f"envelope.archive_format={archive_format!r}; only tar.zst is supported"
        )
    expires_at = envelope.get("expires_at")
    if expires_at is not None and not isinstance(expires_at, str):
        raise BundleEnvelopeError("envelope.expires_at must be ISO-8601 string or null")
    attestation = envelope.get("attestation")
    if attestation is not None and not isinstance(attestation, dict):
        raise BundleEnvelopeError("envelope.attestation must be object or null")
    return {
        "url": url,
        "sha256": sha256.lower(),
        "size_bytes": size_bytes,
        "archive_format": archive_format,
        "content_type": envelope.get("content_type"),
        "expires_at": expires_at,
        "attestation": attestation,
    }


def _check_expiry(envelope: dict[str, Any]) -> None:
    expires = envelope.get("expires_at")
    if not expires:
        return
    try:
        # Tolerate trailing ``Z`` (Python <3.11 strict ISO parser doesn't accept it).
        normalised = expires.replace("Z", "+00:00")
        deadline = datetime.fromisoformat(normalised)
    except ValueError as exc:
        raise BundleEnvelopeError(f"envelope.expires_at not ISO-8601: {expires!r}") from exc
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if datetime.now(UTC) >= deadline:
        raise BundleExpiredError(f"bundle URL already expired at {deadline.isoformat()}")


def _resolve_size_cap(source: Any, kind: str, envelope: dict[str, Any]) -> int:
    """Pick the strictest of:
    - hard global cap
    - per-kind cap from the source's policies_cache
    - per-kind default cap
    - the envelope's own size_bytes
    """
    caps: list[int] = [_GLOBAL_HARD_CAP_BYTES]

    policies = getattr(source, "policies_cache", None) or {}
    if isinstance(policies, dict):
        max_map = policies.get("max_bundle_size_bytes") or policies.get("max_bundle_bytes")
        if isinstance(max_map, dict):
            kc = max_map.get(kind)
            if isinstance(kc, int) and kc > 0:
                caps.append(kc)
        elif isinstance(max_map, int) and max_map > 0:
            caps.append(max_map)

    default = _DEFAULT_MAX_BUNDLE_BYTES.get(kind)
    if default:
        caps.append(default)

    env_size = envelope.get("size_bytes")
    if isinstance(env_size, int) and env_size > 0:
        caps.append(env_size)

    return min(caps)


# ---------------------------------------------------------------------------
# Attestation verification
# ---------------------------------------------------------------------------


def _capabilities_set(source: Any) -> set[str]:
    raw = getattr(source, "capabilities_cache", None)
    if isinstance(raw, list):
        return {str(c) for c in raw}
    if isinstance(raw, dict):
        caps = raw.get("capabilities")
        if isinstance(caps, list):
            return {str(c) for c in caps}
    return set()


def _b64decode_strict(s: str) -> bytes:
    # Accept both standard and URL-safe base64; reject anything else.
    try:
        return base64.b64decode(s, validate=True)
    except (ValueError, base64.binascii.Error):
        try:
            return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
        except (ValueError, base64.binascii.Error) as exc:
            raise AttestationError(f"attestation field is not valid base64: {s[:32]}...") from exc


def verify_attestation(
    source: Any,
    envelope: dict[str, Any],
    bundle_sha256: str,
) -> bool:
    """Verify the envelope.attestation ed25519 signature over the bundle sha256.

    Returns:
      - True if verification ran AND succeeded.
      - False if no verification was required (no attestation OR source
        does not advertise ``attestations`` OR no pinned pubkey AND none
        in envelope to bootstrap from).

    Raises:
      :class:`AttestationError` when verification was required AND failed.
    """
    attestation = envelope.get("attestation")
    if not isinstance(attestation, dict):
        return False

    capabilities = _capabilities_set(source)
    if "attestations" not in capabilities:
        # Source doesn't advertise the capability — ignore the field
        # (treat as bonus metadata only). The plan: "verify the signature
        # ... AND the source advertises attestations capability".
        logger.debug(
            "verify_attestation: source %s advertises no 'attestations' "
            "capability; skipping verification",
            getattr(source, "handle", source),
        )
        return False

    pubkey_b64 = getattr(source, "attestation_pubkey", None)
    # If we don't have a cached pubkey but the envelope offers a public_key
    # (TOFU-bootstrap), accept it once and the caller MUST persist it.
    bootstrap = False
    if not pubkey_b64:
        candidate = attestation.get("public_key")
        if isinstance(candidate, str) and candidate:
            pubkey_b64 = candidate
            bootstrap = True
        else:
            raise AttestationError(
                "envelope advertises attestation but source has no pinned "
                "attestation_pubkey and envelope provides no public_key"
            )

    signature_b64 = attestation.get("signature")
    algorithm = attestation.get("algorithm", "ed25519")
    if algorithm.lower() != "ed25519":
        raise AttestationError(f"unsupported attestation algorithm: {algorithm!r}")
    if not isinstance(signature_b64, str) or not signature_b64:
        raise AttestationError("attestation.signature missing or not a string")

    try:
        pubkey_bytes = _b64decode_strict(pubkey_b64)
        signature_bytes = _b64decode_strict(signature_b64)
    except AttestationError:
        raise
    if len(pubkey_bytes) != 32:
        raise AttestationError(f"ed25519 public key must be 32 bytes; got {len(pubkey_bytes)}")
    verify_key = VerifyKey(pubkey_bytes)

    # Sign the lowercase hex sha256 (most hubs do it this way; matches the
    # marketplace service in packages/tesslate-marketplace/app/services/attestations.py).
    message = bundle_sha256.lower().encode("ascii")
    try:
        verify_key.verify(message, signature_bytes)
    except BadSignatureError as exc:
        raise AttestationError(
            f"ed25519 signature verification failed for sha256 {bundle_sha256}"
        ) from exc

    if bootstrap:
        try:
            source.attestation_pubkey = pubkey_b64
        except (AttributeError, Exception) as exc:  # noqa: BLE001
            logger.debug(
                "verify_attestation: could not bootstrap-cache pubkey on source: %s",
                exc,
            )
    return True


# ---------------------------------------------------------------------------
# Download with streaming sha256 + size verification
# ---------------------------------------------------------------------------


async def _download_and_verify(
    url: str,
    expected_sha256: str,
    max_bytes: int,
    dest_tmp: Path,
    *,
    http: httpx.AsyncClient | None = None,
) -> tuple[str, int]:
    """Stream ``url`` → ``dest_tmp``; refuse on size cap or sha256 mismatch.

    Returns ``(actual_sha256, bytes_written)``.
    """
    own_client = http is None
    client = http or httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT)
    hasher = hashlib.sha256()
    bytes_written = 0
    try:
        async with client.stream("GET", url) as resp:
            if resp.status_code >= 400:
                raise InstallError(
                    f"download failed for {url}: HTTP {resp.status_code}",
                    reason="download_http_error",
                )
            with dest_tmp.open("wb") as f:
                async for chunk in resp.aiter_bytes(_STREAM_CHUNK_BYTES):
                    if not chunk:
                        continue
                    bytes_written += len(chunk)
                    if bytes_written > max_bytes:
                        raise BundleSizeExceededError(
                            f"download exceeded cap {max_bytes} bytes (already {bytes_written})"
                        )
                    hasher.update(chunk)
                    f.write(chunk)
    except (httpx.TransportError, httpx.TimeoutException) as exc:
        raise InstallError(
            f"download transport error: {exc}",
            reason="download_transport_error",
        ) from exc
    finally:
        if own_client:
            await client.aclose()

    actual = hasher.hexdigest()
    if actual.lower() != expected_sha256.lower():
        raise BundleSha256MismatchError(
            f"sha256 mismatch: expected {expected_sha256}, got {actual}"
        )
    return actual, bytes_written


# ---------------------------------------------------------------------------
# Local short-circuit
# ---------------------------------------------------------------------------


async def _install_from_local_source(
    *,
    source: Any,
    kind: str,
    slug: str,
    version: str | None,
    dest_root_override: Path | None,
) -> InstallResult:
    """Install when ``source.base_url.startswith('local://')``.

    Bypasses HTTP — the marketplace_client never makes a network call
    for local sources. We still:
      - hash the bundle and verify size against per-kind cap
      - extract via safe_extract (path-traversal hardened)
      - atomic rename staging → final
    """
    envelope_obj = marketplace_local.get_bundle_envelope(kind, slug, version)
    envelope = envelope_obj.to_dict()
    parsed = _parse_envelope(envelope)
    cap = _resolve_size_cap(source, kind, parsed)
    if parsed["size_bytes"] > cap:
        raise BundleSizeExceededError(
            f"local bundle for {kind}/{slug}@{envelope_obj.url} "
            f"size {parsed['size_bytes']} exceeds cap {cap}"
        )

    target = dest_root_override or _default_install_dir(kind, slug)
    if target.exists():
        raise AlreadyInstalledError(f"already installed: {kind}/{slug}")

    staging = target.with_suffix(".installing")
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=False)

    bundle_tmp = staging / "_bundle.tar.zst"
    try:
        marketplace_local.materialise_bundle(envelope_obj, bundle_tmp)
        # Re-hash to verify on-disk integrity (defense in depth).
        h = hashlib.sha256()
        with bundle_tmp.open("rb") as f:
            while True:
                chunk = f.read(_STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                h.update(chunk)
        actual = h.hexdigest()
        if actual.lower() != parsed["sha256"]:
            raise BundleSha256MismatchError(
                f"local bundle sha256 mismatch: expected {parsed['sha256']}, got {actual}"
            )
        # Extract into a sibling dir, then move contents up.
        extract_root = staging / "_extract"
        extract_root.mkdir()
        try:
            safe_extract(bundle_tmp, extract_root)
        except (UnsafeArchiveError, ArchiveTooLargeError) as exc:
            raise InstallError(
                f"local bundle extraction refused: {exc}",
                reason=getattr(exc, "reason", "unsafe_archive"),
            ) from exc

        # Move extracted files into staging root (skipping the bundle + extract dir
        # which are internal).
        for entry in extract_root.iterdir():
            shutil.move(str(entry), str(staging / entry.name))
        shutil.rmtree(extract_root, ignore_errors=True)
        bundle_tmp.unlink(missing_ok=True)

        _write_install_manifest(
            staging,
            source_handle=getattr(source, "handle", "local"),
            kind=kind,
            slug=slug,
            version=envelope_obj.url.split("/")[-1] if version is None else version,
            sha256=parsed["sha256"],
            size_bytes=parsed["size_bytes"],
            install_id=None,
        )

        target.parent.mkdir(parents=True, exist_ok=True)
        staging.replace(target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return InstallResult(
        kind=kind,
        slug=slug,
        version=str(version or ""),
        path=target,
        sha256=parsed["sha256"],
        size_bytes=parsed["size_bytes"],
        source_handle=getattr(source, "handle", "local"),
        install_id=None,
    )


# ---------------------------------------------------------------------------
# Per-source install (the new Wave 6 primary path)
# ---------------------------------------------------------------------------


async def install_from_source(
    *,
    source: Any,
    kind: str,
    slug: str,
    version: str | None = None,
    decrypted_token: str | None = None,
    client: MarketplaceClient | None = None,  # noqa: F821
    dest_root_override: Path | None = None,
) -> InstallResult:
    """Install ``{kind, slug, version}`` from ``source``.

    The installer's per-source primary entrypoint after Wave 6. ``source``
    is a :class:`models.MarketplaceSource` row (or any duck-type with the
    same attribute surface — used by tests).

    On ``local://`` sources we short-circuit to the filesystem; otherwise
    we use the federation marketplace_client to fetch the envelope, then
    download / verify / extract.
    """
    _validate_kind(kind)
    _validate_slug(slug)

    base_url = getattr(source, "base_url", None) or ""
    if base_url.startswith(marketplace_local.LOCAL_BASE_URL_PREFIX):
        return await _install_from_local_source(
            source=source,
            kind=kind,
            slug=slug,
            version=version,
            dest_root_override=dest_root_override,
        )

    # HTTP path — fetch the envelope via the source's client.
    # Imported lazily to avoid a circular import (federation → installer).
    from .marketplace_client import make_client_from_source

    target = dest_root_override or _default_install_dir(kind, slug)
    if target.exists():
        raise AlreadyInstalledError(f"already installed: {kind}/{slug}")

    owns_client = client is None
    if client is None:
        client = make_client_from_source(
            source,
            decrypted_token=decrypted_token,
            base_url=base_url,
        )

    try:
        # If version unspecified, ask the source for the latest.
        if version is None:
            try:
                item = await client.get_item(kind, slug)
            except Exception as exc:
                raise InstallError(
                    f"could not resolve item {kind}/{slug}: {exc}",
                    reason="item_resolve_failed",
                ) from exc
            latest = item.get("latest_version") if isinstance(item, dict) else None
            if isinstance(latest, str) and latest:
                version = latest
            else:
                # Fall back to listing versions.
                versions = await client.list_versions(kind, slug)
                if not versions:
                    raise InstallError(
                        f"source has no versions for {kind}/{slug}",
                        reason="no_versions",
                    )
                version = str(versions[0].get("version"))

        try:
            envelope_raw = await client.get_bundle(kind, slug, version)
        except Exception as exc:
            raise InstallError(
                f"could not fetch bundle envelope for {kind}/{slug}@{version}: {exc}",
                reason="bundle_envelope_fetch_failed",
            ) from exc

        envelope = _parse_envelope(envelope_raw)
        _check_expiry(envelope)
        cap = _resolve_size_cap(source, kind, envelope)
        if envelope["size_bytes"] > cap:
            raise BundleSizeExceededError(
                f"envelope.size_bytes {envelope['size_bytes']} exceeds cap {cap} for {kind}"
            )

        staging = target.with_suffix(".installing")
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=False)

        bundle_tmp = staging / "_bundle.tar.zst"
        try:
            # Signed URLs are external; do NOT carry the source's bearer.
            async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT) as http:
                actual_sha, written = await _download_and_verify(
                    envelope["url"],
                    envelope["sha256"],
                    cap,
                    bundle_tmp,
                    http=http,
                )

            # Attestation: verify after sha256 confirms integrity.
            verify_attestation(source, envelope, actual_sha)

            extract_root = staging / "_extract"
            extract_root.mkdir()
            try:
                safe_extract(bundle_tmp, extract_root)
            except (UnsafeArchiveError, ArchiveTooLargeError) as exc:
                raise InstallError(
                    f"bundle extraction refused: {exc}",
                    reason=getattr(exc, "reason", "unsafe_archive"),
                ) from exc

            # Promote extracted files up; remove internal dirs.
            for entry in extract_root.iterdir():
                shutil.move(str(entry), str(staging / entry.name))
            shutil.rmtree(extract_root, ignore_errors=True)
            bundle_tmp.unlink(missing_ok=True)

            _write_install_manifest(
                staging,
                source_handle=getattr(source, "handle", "unknown"),
                kind=kind,
                slug=slug,
                version=version,
                sha256=actual_sha,
                size_bytes=written,
                install_id=None,
            )

            target.parent.mkdir(parents=True, exist_ok=True)
            staging.replace(target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

        return InstallResult(
            kind=kind,
            slug=slug,
            version=version,
            path=target,
            sha256=actual_sha,
            size_bytes=written,
            source_handle=getattr(source, "handle", "unknown"),
            install_id=None,
        )
    finally:
        if owns_client:
            await client.aclose()


# ---------------------------------------------------------------------------
# Cloud-mediated fallback (the legacy desktop path) — preserved for sources
# that explicitly require it (e.g. paid Tesslate Official items).
# ---------------------------------------------------------------------------


async def _initiate_cloud_install(cloud: CloudClient, kind: str, slug: str) -> dict[str, Any]:
    try:
        resp = await cloud.post(
            "/api/v1/marketplace/install",
            json={"kind": kind, "slug": slug},
        )
    except NotPairedError:
        raise
    except CircuitOpenError as exc:
        raise CloudFallbackUnavailableError(f"cloud unavailable: {exc}") from exc
    except (httpx.TransportError, httpx.TimeoutException) as exc:
        raise CloudFallbackUnavailableError(f"cloud transport error: {exc}") from exc

    if resp.status_code >= 400:
        raise InstallError(
            f"cloud install initiate failed: HTTP {resp.status_code}",
            reason="cloud_initiate_failed",
        )
    try:
        body = resp.json()
    except ValueError as exc:
        raise InstallError(
            f"cloud returned non-JSON body: {exc}",
            reason="cloud_bad_response",
        ) from exc

    if not isinstance(body, dict):
        raise InstallError("cloud returned non-object body", reason="cloud_bad_response")
    install_id = body.get("install_id")
    urls = body.get("download_urls")
    manifest = body.get("manifest")
    if not isinstance(install_id, str) or not install_id:
        raise InstallError("cloud response missing install_id", reason="cloud_bad_response")
    if not isinstance(urls, list) or not urls:
        raise InstallError("cloud response missing download_urls", reason="cloud_bad_response")
    if not isinstance(manifest, dict):
        raise InstallError("cloud response missing manifest", reason="cloud_bad_response")
    return body


async def _ack_cloud_install(cloud: CloudClient, install_id: str) -> None:
    try:
        resp = await cloud.post(
            f"/api/v1/marketplace/install/{install_id}/ack",
            json={},
        )
        if resp.status_code >= 400:
            logger.warning(
                "marketplace_installer: ack returned %s for %s",
                resp.status_code,
                install_id,
            )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — ack is non-blocking
        logger.warning("marketplace_installer: ack failed for %s: %s", install_id, exc)


async def _install_via_cloud(kind: str, slug: str) -> InstallResult:
    """Original cloud-mediated install: cloud emits signed URLs and
    sha256s for the bundle's individual files, the desktop downloads
    each, atomic rename. Preserved for sources that require it.

    Note this path does NOT use bundle attestation — the cloud is the
    trust anchor and signs the URLs.
    """
    target = _default_install_dir(kind, slug)
    if target.exists():
        raise AlreadyInstalledError(f"already installed: {kind}/{slug}")

    client = await get_cloud_client()
    body = await _initiate_cloud_install(client, kind, slug)
    install_id: str = body["install_id"]
    download_urls: list[dict[str, Any]] = body["download_urls"]
    manifest: dict[str, Any] = dict(body["manifest"])

    staging = target.with_suffix(".installing")
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=False)

    total_bytes = 0
    try:
        async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT) as http:
            for entry in download_urls:
                if not isinstance(entry, dict):
                    raise InstallError("invalid download_urls entry", reason="cloud_bad_response")
                url = entry.get("url")
                sha256 = entry.get("sha256")
                name = entry.get("name")
                if not (isinstance(url, str) and isinstance(sha256, str) and isinstance(name, str)):
                    raise InstallError(
                        "download entry missing url/sha256/name",
                        reason="cloud_bad_response",
                    )
                if "/" in name or name.startswith(".."):
                    raise InvalidSlugError(f"invalid download name: {name}")
                dest = staging / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(dest.suffix + ".part")
                _, written = await _download_and_verify(
                    url,
                    sha256,
                    _GLOBAL_HARD_CAP_BYTES,
                    tmp,
                    http=http,
                )
                tmp.replace(dest)
                total_bytes += written

        manifest_payload = {
            **manifest,
            "source": "cloud",
            "installed_from": "cloud",
            "install_id": install_id,
        }
        manifest_tmp = staging / "manifest.json.part"
        manifest_tmp.write_text(
            json.dumps(manifest_payload, indent=2),
            encoding="utf-8",
        )
        manifest_tmp.replace(staging / "manifest.json")

        target.parent.mkdir(parents=True, exist_ok=True)
        staging.replace(target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    await _ack_cloud_install(client, install_id)
    return InstallResult(
        kind=kind,
        slug=slug,
        version=str(manifest.get("version") or ""),
        path=target,
        sha256="cloud-mediated",
        size_bytes=total_bytes,
        source_handle="cloud",
        install_id=install_id,
    )


# ---------------------------------------------------------------------------
# Desktop entrypoint kept for back-compat with routers/marketplace_local.py
# ---------------------------------------------------------------------------


async def install(kind: str, slug: str) -> InstallResult:
    """Legacy desktop entrypoint — cloud-mediated install.

    Preserved as the fallback path; new callers should prefer
    :func:`install_from_source`. Kept as the default behaviour of
    ``POST /api/desktop/marketplace/install`` until the desktop UI is
    threaded with explicit source selection (subsequent waves).
    """
    return await _install_via_cloud(kind, slug)


# ---------------------------------------------------------------------------
# Manifest writer
# ---------------------------------------------------------------------------


def _write_install_manifest(
    staging: Path,
    *,
    source_handle: str,
    kind: str,
    slug: str,
    version: str,
    sha256: str,
    size_bytes: int,
    install_id: str | None,
) -> None:
    """Write/merge the per-install manifest.json with provenance fields.

    If the bundle already shipped a ``manifest.json`` we preserve its
    keys and overlay our provenance fields on top.
    """
    out = staging / "manifest.json"
    existing: dict[str, Any] = {}
    if out.is_file():
        try:
            existing = json.loads(out.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {}
        except (OSError, json.JSONDecodeError):
            existing = {}

    merged = {
        **existing,
        "source": source_handle,
        "installed_from": "marketplace",
        "kind": kind,
        "slug": slug,
        "version": version,
        "bundle_sha256": sha256,
        "bundle_size_bytes": size_bytes,
        "install_id": install_id,
        "installed_at": datetime.now(UTC).isoformat(),
    }
    tmp = out.with_suffix(".json.part")
    tmp.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    tmp.replace(out)


# ---------------------------------------------------------------------------
# Uninstall — unchanged from the previous revision
# ---------------------------------------------------------------------------


async def uninstall(kind: str, slug: str) -> bool:
    """Remove the install directory. Returns True if something was removed."""
    target = _default_install_dir(kind, slug)
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True


__all__ = [
    "AlreadyInstalledError",
    "AttestationError",
    "BundleEnvelopeError",
    "BundleExpiredError",
    "BundleFormatError",
    "BundleSha256MismatchError",
    "BundleSizeExceededError",
    "CloudFallbackUnavailableError",
    "InstallError",
    "InstallResult",
    "InvalidKindError",
    "InvalidSlugError",
    "install",
    "install_from_source",
    "install_path",
    "uninstall",
    "verify_attestation",
]
