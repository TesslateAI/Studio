"""Public download surface for the desktop installer + Tauri auto-updater.

Exposes two unauthenticated GET endpoints under `/desktop/releases`:

  - `/desktop/releases/latest.json`  — Tauri v2 update manifest.
    Returns the JSON shape `tauri-plugin-updater` expects, generated on
    demand from the latest GitHub release matching the configured tag
    prefix (default `desktop-v*`).
  - `/desktop/releases/{filename}`   — 302-redirects to the matching
    release asset's `browser_download_url`. The orchestrator never
    streams the bytes itself — they stay on GitHub's CDN.

This is a stable public surface anchored at `your-domain.com` (or
whatever `app_base_url` resolves to) so the Tauri updater endpoint in
`tauri.conf.json` and the `install.{sh,ps1}` download scripts can hard-code
one URL without coupling to GitHub's release URL shape.

Configuration (all optional, all `Settings`):

  desktop_releases_github_repo   "owner/repo"   default: "TesslateAI/OpenSail"
  desktop_releases_github_token  PAT            optional; private repo / rate limit
  desktop_releases_tag_prefix    str            default: "desktop-v"

Caching: GitHub responses are memoised for 5 minutes in-process. The first
hit per pod after a deploy pays the GitHub round trip; subsequent hits
are O(dict lookup).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/desktop/releases", tags=["desktop-releases"])

_GITHUB_API = "https://api.github.com"
_CACHE_TTL_SECONDS = 300  # 5 minutes


# ── Tauri target keys ─────────────────────────────────────────────────────────
# Map from Tauri target triple to a regex matching the corresponding updater
# asset name. Each release asset is matched against every regex in order; first
# hit wins. Patterns are intentionally loose because `cargo tauri build`
# filenames carry the app version we don't know until we read the release.
#
# Tauri v2 with `bundle.createUpdaterArtifacts: true` produces the native v2
# format — the installer itself IS the updater payload, with a `.sig` sibling
# carrying the minisign signature. (Earlier v2 "v1Compatible" mode wrapped
# Linux/Windows installers in a `.tar.gz` archive; that mode is not used here.)
#
#   linux-x86_64:    *_amd64.AppImage             (+ .sig sibling)
#   darwin-x86_64:   *_x64.app.tar.gz             (.app is a directory bundle,
#                                                  so still wrapped in tar.gz)
#   darwin-aarch64:  *_aarch64.app.tar.gz         (+ .sig sibling)
#   windows-x86_64:  *_x64-setup.exe              (NSIS, + .sig sibling)
#
# Naming may diverge across tauri-cli versions; add additional regexes here
# rather than mutating existing ones.
_TARGETS: dict[str, re.Pattern[str]] = {
    "linux-x86_64": re.compile(r".*_amd64\.AppImage$"),
    "darwin-x86_64": re.compile(r".*_x64\.app\.tar\.gz$"),
    "darwin-aarch64": re.compile(r".*_aarch64\.app\.tar\.gz$"),
    "windows-x86_64": re.compile(r".*_x64-setup\.exe$"),
}


@dataclass
class _CachedRelease:
    payload: dict[str, Any]
    fetched_at: float


_cache: _CachedRelease | None = None
_cache_lock = asyncio.Lock()


def _github_repo() -> str:
    return getattr(get_settings(), "desktop_releases_github_repo", "TesslateAI/OpenSail")


def _github_token() -> str | None:
    tok = getattr(get_settings(), "desktop_releases_github_token", "") or None
    return tok if tok else None


def _tag_prefix() -> str:
    return getattr(get_settings(), "desktop_releases_tag_prefix", "desktop-v")


def _public_base_url(request: Request) -> str:
    """Resolve the externally-visible base URL the manifest should advertise.

    Prefers `settings.app_base_url` (the deployment's canonical
    `https://your-domain.com`-style URL) so the manifest stays correct
    even when the orchestrator pod is reached via an internal hostname.
    Falls back to the request's own scheme+host.
    """
    configured = (getattr(get_settings(), "app_base_url", "") or "").rstrip("/")
    if configured:
        return configured
    return f"{request.url.scheme}://{request.url.netloc}"


async def _fetch_latest_release() -> dict[str, Any] | None:
    """Return the latest GitHub release matching the configured tag prefix.

    GitHub's `/releases/latest` only returns the most recent *non-prerelease*,
    but `desktop-release.yml` publishes with `prerelease: true`, so we have
    to iterate `/releases` and filter by tag prefix.

    Returns `None` if no matching release exists or the GitHub call fails;
    the caller surfaces a clean 404.
    """
    repo = _github_repo()
    url = f"{_GITHUB_API}/repos/{repo}/releases?per_page=30"
    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = _github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("desktop_releases: GitHub API unreachable: %s", exc)
        return None

    if resp.status_code != 200:
        logger.warning(
            "desktop_releases: GitHub API returned %s for %s",
            resp.status_code,
            url,
        )
        return None

    prefix = _tag_prefix()
    releases = resp.json()
    if not isinstance(releases, list):
        return None

    for release in releases:
        tag = release.get("tag_name") or ""
        if tag.startswith(prefix) and not release.get("draft"):
            return release
    return None


async def _cached_release() -> dict[str, Any] | None:
    """In-process TTL cache around `_fetch_latest_release`."""
    global _cache
    now = time.monotonic()
    if _cache and now - _cache.fetched_at < _CACHE_TTL_SECONDS:
        return _cache.payload

    async with _cache_lock:
        # Re-check under lock — another coroutine may have populated it.
        if _cache and time.monotonic() - _cache.fetched_at < _CACHE_TTL_SECONDS:
            return _cache.payload
        release = await _fetch_latest_release()
        if release is None:
            return None
        _cache = _CachedRelease(payload=release, fetched_at=time.monotonic())
        return release


def _parse_version(tag: str) -> str:
    """Strip the configured tag prefix to recover the semver string."""
    prefix = _tag_prefix()
    return tag[len(prefix) :] if tag.startswith(prefix) else tag


async def _signature_for(asset_name: str, all_assets: list[dict[str, Any]]) -> str:
    """Download the contents of the matching `.sig` sibling asset.

    The Tauri v2 updater expects the `signature` field in latest.json to be
    the literal minisign signature text (one short line), not a URL. The
    sidecar caller is wrapped in a 5-minute TTL cache so the extra round trip
    per platform happens at most once per cache window.

    Returns "" when no `.sig` sibling is published — the updater will then
    refuse the update (correct behavior for unsigned builds).
    """
    sig_name = f"{asset_name}.sig"
    sig_url: str | None = None
    for asset in all_assets:
        if asset.get("name") == sig_name:
            sig_url = asset.get("browser_download_url")
            break
    if not sig_url:
        return ""

    headers: dict[str, str] = {"Accept": "application/octet-stream"}
    token = _github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(sig_url, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("desktop_releases: .sig fetch failed for %s: %s", sig_name, exc)
        return ""
    if resp.status_code != 200:
        logger.warning(
            "desktop_releases: .sig fetch %s returned %s",
            sig_name,
            resp.status_code,
        )
        return ""
    return resp.text.strip()


@router.get("/latest.json")
async def latest_manifest(request: Request) -> dict[str, Any]:
    """Return the Tauri v2 update manifest for the latest desktop release."""
    release = await _cached_release()
    if release is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No desktop releases published yet. "
                f"Configure DESKTOP_RELEASES_GITHUB_REPO (current: {_github_repo()}) "
                f"and publish a release tagged {_tag_prefix()}<semver>."
            ),
        )

    version = _parse_version(release.get("tag_name") or "")
    notes = release.get("body") or ""
    pub_date = release.get("published_at") or release.get("created_at") or ""
    assets: list[dict[str, Any]] = release.get("assets") or []
    base = _public_base_url(request)

    platforms: dict[str, dict[str, str]] = {}
    for target, pattern in _TARGETS.items():
        for asset in assets:
            name = asset.get("name") or ""
            if pattern.match(name):
                platforms[target] = {
                    "signature": await _signature_for(name, assets),
                    # Point back at our own surface so the canonical URL is
                    # your-domain.com, not GitHub's CDN. The
                    # `/{filename}` route below 302s to the actual GitHub
                    # download URL.
                    "url": f"{base}/desktop/releases/{name}",
                }
                break

    return {
        "version": version,
        "notes": notes,
        "pub_date": pub_date,
        "platforms": platforms,
    }


@router.get("/{filename:path}")
async def download_asset(filename: str) -> RedirectResponse:
    """Redirect to the matching release asset's `browser_download_url`.

    `latest.json` is handled by its own route above; any other `{filename}`
    is looked up in the latest release's assets and 302-redirected to
    GitHub's CDN. Keeps the orchestrator out of the binary-bandwidth path.
    """
    # The route above catches /latest.json specifically; defense-in-depth
    # against future router-ordering changes — `latest.json` is metadata,
    # not a downloadable asset.
    if filename == "latest.json":
        raise HTTPException(status_code=404)

    release = await _cached_release()
    if release is None:
        raise HTTPException(status_code=404, detail="No desktop releases available.")

    for asset in release.get("assets") or []:
        if asset.get("name") == filename:
            url = asset.get("browser_download_url")
            if not url:
                raise HTTPException(status_code=502, detail="Asset has no download URL.")
            # 302 (not 301) so future releases that rename or move the
            # asset aren't permanently cached by clients.
            return RedirectResponse(url=url, status_code=302)

    raise HTTPException(
        status_code=404,
        detail=f"Asset {filename!r} not found in latest release.",
    )


__all__ = ["router"]
