"""
Desktop marketplace installer.

Drives the cloud-mediated install flow for marketplace items (agent / skill /
base / theme) on the desktop shell:

  1. ``POST /api/v1/marketplace/install`` with ``{kind, slug}`` via
     :class:`CloudClient` — cloud responds with signed download URLs, their
     SHA-256 digests, and the canonical manifest.
  2. Stream each download to a tmp file with a bearer-less ``httpx.AsyncClient``
     (signed S3/R2 URLs MUST NOT carry the cloud bearer), verifying SHA-256 as
     bytes arrive. Files land in ``$TESSLATE_STUDIO_HOME/{kind}s/{slug}/`` via
     atomic rename so a mid-stream crash never leaves partial files.
  3. Write ``manifest.json`` with ``{...cloud_manifest, source: "local",
     installed_from: "cloud", install_id}``.
  4. Best-effort ``POST /api/v1/marketplace/install/{install_id}/ack``. Ack
     failure is logged but NEVER raised — the item is already installed.

All failure modes surface as :class:`InstallError` with a human-readable
reason so the router can map them to a clean 4xx/5xx without leaking httpx
internals.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .cloud_client import (
    CircuitOpenError,
    CloudClient,
    NotPairedError,
    get_cloud_client,
)
from .desktop_paths import resolve_studio_home

logger = logging.getLogger(__name__)

_KIND_TO_DIR: dict[str, str] = {
    "agent": "agents",
    "skill": "skills",
    "base": "bases",
    "theme": "themes",
}

_DOWNLOAD_TIMEOUT = httpx.Timeout(60.0)
_STREAM_CHUNK_BYTES = 64 * 1024


class InstallError(Exception):
    """Domain error raised for any installer failure with a safe message."""


@dataclass(frozen=True)
class InstallResult:
    kind: str
    slug: str
    path: Path
    install_id: str


def _install_dir(kind: str, slug: str) -> Path:
    if kind not in _KIND_TO_DIR:
        raise InstallError(f"unknown kind: {kind}")
    if not slug or "/" in slug or ".." in slug:
        raise InstallError(f"invalid slug: {slug}")
    return resolve_studio_home() / _KIND_TO_DIR[kind] / slug


def install_path(kind: str, slug: str) -> Path:
    """Public helper: resolve the on-disk path for ``{kind}/{slug}``."""
    return _install_dir(kind, slug)


async def _download_and_verify(
    http: httpx.AsyncClient, url: str, sha256: str, dest_tmp: Path
) -> None:
    """Stream ``url`` → ``dest_tmp``, verifying SHA-256 as we go."""
    hasher = hashlib.sha256()
    try:
        async with http.stream("GET", url) as resp:
            if resp.status_code >= 400:
                raise InstallError(
                    f"download failed ({resp.status_code}) for {url}"
                )
            with dest_tmp.open("wb") as f:
                async for chunk in resp.aiter_bytes(_STREAM_CHUNK_BYTES):
                    if not chunk:
                        continue
                    hasher.update(chunk)
                    f.write(chunk)
    except asyncio.CancelledError:
        raise
    except InstallError:
        raise
    except (httpx.TransportError, httpx.TimeoutException) as exc:
        raise InstallError(f"download transport error: {exc}") from exc

    digest = hasher.hexdigest()
    if digest.lower() != sha256.lower():
        raise InstallError(
            f"sha256 mismatch for {url}: expected {sha256}, got {digest}"
        )


async def _initiate_install(
    client: CloudClient, kind: str, slug: str
) -> dict[str, Any]:
    try:
        resp = await client.post(
            "/api/v1/marketplace/install", json={"kind": kind, "slug": slug}
        )
    except NotPairedError:
        raise
    except CircuitOpenError as exc:
        raise InstallError(f"cloud unavailable: {exc}") from exc
    except (httpx.TransportError, httpx.TimeoutException) as exc:
        raise InstallError(f"cloud transport error: {exc}") from exc

    if resp.status_code >= 400:
        raise InstallError(
            f"cloud install initiate failed: HTTP {resp.status_code}"
        )
    try:
        body = resp.json()
    except ValueError as exc:
        raise InstallError(f"cloud returned non-JSON body: {exc}") from exc

    install_id = body.get("install_id")
    urls = body.get("download_urls")
    manifest = body.get("manifest")
    if not isinstance(install_id, str) or not install_id:
        raise InstallError("cloud response missing install_id")
    if not isinstance(urls, list) or not urls:
        raise InstallError("cloud response missing download_urls")
    if not isinstance(manifest, dict):
        raise InstallError("cloud response missing manifest")
    return body


async def _ack_install(client: CloudClient, install_id: str) -> None:
    """Best-effort ack. Never raises."""
    try:
        resp = await client.post(
            f"/api/v1/marketplace/install/{install_id}/ack", json={}
        )
        if resp.status_code >= 400:
            logger.warning(
                "marketplace_installer: ack returned %s for %s",
                resp.status_code,
                install_id,
            )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — ack is explicitly non-blocking
        logger.warning(
            "marketplace_installer: ack failed for %s: %s", install_id, exc
        )


async def install(kind: str, slug: str) -> InstallResult:
    """Run the full install pipeline; raise :class:`InstallError` on failure."""
    target = _install_dir(kind, slug)
    if target.exists():
        raise InstallError(f"already installed: {kind}/{slug}")

    client = await get_cloud_client()
    body = await _initiate_install(client, kind, slug)
    install_id: str = body["install_id"]
    download_urls: list[dict[str, Any]] = body["download_urls"]
    manifest: dict[str, Any] = dict(body["manifest"])

    staging = target.with_suffix(".installing")
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=False)

    try:
        # Signed download URLs are cross-origin (S3/R2) and MUST NOT carry the
        # cloud bearer — use a dedicated httpx client with no auth injection.
        async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT) as http:
            for entry in download_urls:
                if not isinstance(entry, dict):
                    raise InstallError("invalid download_urls entry")
                url = entry.get("url")
                sha256 = entry.get("sha256")
                name = entry.get("name")
                if not (isinstance(url, str) and isinstance(sha256, str) and isinstance(name, str)):
                    raise InstallError("download entry missing url/sha256/name")
                if "/" in name or name.startswith(".."):
                    raise InstallError(f"invalid download name: {name}")
                dest = staging / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(dest.suffix + ".part")
                await _download_and_verify(http, url, sha256, tmp)
                tmp.replace(dest)

        manifest_payload = {
            **manifest,
            "source": "local",
            "installed_from": "cloud",
            "install_id": install_id,
        }
        manifest_tmp = staging / "manifest.json.part"
        manifest_tmp.write_text(
            json.dumps(manifest_payload, indent=2),
            encoding="utf-8",
        )
        manifest_tmp.replace(staging / "manifest.json")

        # Atomic move: staging → target.
        staging.replace(target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    await _ack_install(client, install_id)
    return InstallResult(kind=kind, slug=slug, path=target, install_id=install_id)


async def uninstall(kind: str, slug: str) -> bool:
    """Remove the install directory. Returns True if something was removed."""
    target = _install_dir(kind, slug)
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True
