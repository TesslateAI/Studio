"""
Desktop-local marketplace router.

Surfaces installed marketplace items (agents / skills / bases / themes) that
live on the desktop filesystem under ``$OPENSAIL_HOME/{kind}s/`` and,
when paired + ``settings.pull_from_cloud`` is on, merges the cloud catalog so
the UI can render a unified dual-source list.

Non-blocking guarantees:
  - Cloud failure (timeout, 5xx, breaker open, NotPaired) NEVER raises out of
    the endpoint — it logs at debug and falls back to local-only items.
  - A 1-hour on-disk cache provides stale-while-revalidate so a slow cloud
    never blocks the foreground list call.

Install pipeline (POST /marketplace/install) is intentionally NOT implemented
in this slice — list + source-tagging is enough to unblock the dual-source
view.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from ..config import get_settings
from ..models import User
from ..services import marketplace_installer, token_store
from ..services.cloud_client import (
    CircuitOpenError,
    NotPairedError,
    get_cloud_client,
)
from ..services.desktop_paths import resolve_opensail_home
from ..users import current_active_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/desktop/marketplace", tags=["desktop-marketplace"])

ItemKind = Literal["agent", "skill", "base", "theme"]
_KIND_TO_DIR: dict[str, str] = {
    "agent": "agents",
    "skill": "skills",
    "base": "bases",
    "theme": "themes",
}
_CACHE_TTL_SECONDS = 3600  # 1h
_CACHE_FILENAME = "marketplace.json"


# ---------------------------------------------------------------------------
# Local scan
# ---------------------------------------------------------------------------


def _scan_local(kind: str) -> list[dict[str, Any]]:
    """Scan ``$OPENSAIL_HOME/{kind}s/*/manifest.json``."""
    home = resolve_opensail_home()
    base = home / _KIND_TO_DIR[kind]
    if not base.exists():
        return []
    items: list[dict[str, Any]] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        manifest = entry / "manifest.json"
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.debug("marketplace_local: skipping %s: %s", manifest, exc)
            continue
        if not isinstance(data, dict):
            continue
        data.setdefault("id", entry.name)
        data.setdefault("slug", entry.name)
        data["kind"] = kind
        data["source"] = "local"
        data["install_path"] = str(entry)
        items.append(data)
    return items


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _cache_path() -> Path:
    return resolve_opensail_home() / "cache" / _CACHE_FILENAME


def _read_cache(kind: str) -> tuple[list[dict[str, Any]] | None, bool]:
    """Return ``(items, fresh)``. ``items`` is None when no entry exists."""
    path = _cache_path()
    if not path.exists():
        return None, False
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, False
    entry = blob.get(kind) if isinstance(blob, dict) else None
    if not isinstance(entry, dict):
        return None, False
    items = entry.get("items")
    ts = entry.get("ts")
    if not isinstance(items, list) or not isinstance(ts, (int, float)):
        return None, False
    fresh = (time.time() - ts) < _CACHE_TTL_SECONDS
    return items, fresh


def _write_cache(kind: str, items: list[dict[str, Any]]) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    blob: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                blob = existing
        except (OSError, json.JSONDecodeError):
            blob = {}
    blob[kind] = {"ts": time.time(), "items": items}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(blob), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Cloud fetch
# ---------------------------------------------------------------------------


async def _fetch_cloud(kind: str) -> list[dict[str, Any]]:
    """Best-effort cloud fetch. Never raises; returns ``[]`` on failure."""
    try:
        client = await get_cloud_client()
        resp = await client.get(f"/api/public/marketplace/{kind}s")
    except (NotPairedError, CircuitOpenError) as exc:
        logger.debug("marketplace_local: cloud fetch skipped (%s): %s", kind, exc)
        return []
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("marketplace_local: cloud fetch errored (%s): %s", kind, exc)
        return []

    if resp.status_code >= 400:
        logger.debug("marketplace_local: cloud returned %s for %s", resp.status_code, kind)
        return []

    try:
        body = resp.json()
    except ValueError:
        return []

    raw = body.get("items") if isinstance(body, dict) else body
    if not isinstance(raw, list):
        return []

    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        item = dict(item)
        item["kind"] = kind
        item["source"] = "cloud"
        out.append(item)
    return out


async def _refresh_cache_in_background(kind: str) -> None:
    """Background task: pull from cloud and rewrite cache for ``kind``.

    Wrapped in try/except so a failing background refresh never bubbles into
    the FastAPI error log loop.
    """
    try:
        local = _scan_local(kind)
        cloud = await _fetch_cloud(kind)
        _write_cache(kind, _merge(local, cloud))
    except Exception as exc:  # pragma: no cover
        logger.debug("marketplace_local: background refresh failed (%s): %s", kind, exc)


def _merge(local: list[dict[str, Any]], cloud: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge local + cloud, de-duped by ``slug`` (local wins)."""
    seen = {item.get("slug") for item in local if item.get("slug")}
    merged = list(local)
    for item in cloud:
        if item.get("slug") in seen:
            continue
        merged.append(item)
    return merged


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/items")
async def list_items(
    background: BackgroundTasks,
    kind: ItemKind = Query(...),
    _user: User = Depends(current_active_user),
) -> dict[str, Any]:
    if kind not in _KIND_TO_DIR:
        raise HTTPException(status_code=400, detail=f"unknown kind: {kind}")

    settings = get_settings()
    cloud_enabled = settings.pull_from_cloud and token_store.is_paired()

    cached, fresh = _read_cache(kind)
    if cached is not None and fresh:
        return {"kind": kind, "items": cached, "cached": True}

    local = _scan_local(kind)

    if not cloud_enabled:
        items = local
        _write_cache(kind, items)
        return {"kind": kind, "items": items, "cached": False}

    if cached is not None:
        # Stale-while-revalidate: serve stale, refresh in background.
        background.add_task(_refresh_cache_in_background, kind)
        return {"kind": kind, "items": cached, "cached": True, "stale": True}

    cloud = await _fetch_cloud(kind)
    items = _merge(local, cloud)
    _write_cache(kind, items)
    return {"kind": kind, "items": items, "cached": False}


# ---------------------------------------------------------------------------
# Install / uninstall
# ---------------------------------------------------------------------------


class InstallRequest(BaseModel):
    kind: ItemKind = Field(...)
    slug: str = Field(..., min_length=1, max_length=200)


def _invalidate_cache(kind: str) -> None:
    """Drop the ``kind`` entry from the on-disk marketplace cache."""
    path = _cache_path()
    if not path.exists():
        return
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(blob, dict) or kind not in blob:
        return
    blob.pop(kind, None)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(blob), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.debug("marketplace_local: cache invalidation failed: %s", exc)


@router.post("/install", status_code=201)
async def install_item(
    body: InstallRequest,
    _user: User = Depends(current_active_user),
) -> dict[str, Any]:
    if marketplace_installer.install_path(body.kind, body.slug).exists():
        raise HTTPException(status_code=409, detail="already installed")
    try:
        result = await marketplace_installer.install(body.kind, body.slug)
    except NotPairedError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except CircuitOpenError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except marketplace_installer.InstallError as exc:
        msg = str(exc)
        if msg.startswith("already installed"):
            raise HTTPException(status_code=409, detail=msg) from exc
        if "cloud" in msg.lower() or "transport" in msg.lower():
            raise HTTPException(status_code=502, detail=msg) from exc
        raise HTTPException(status_code=400, detail=msg) from exc

    _invalidate_cache(body.kind)
    return {
        "kind": result.kind,
        "slug": result.slug,
        "install_id": result.install_id,
        "path": str(result.path),
    }


@router.delete("/install/{kind}/{slug}", status_code=204)
async def uninstall_item(
    kind: ItemKind,
    slug: str,
    _user: User = Depends(current_active_user),
) -> Response:
    try:
        removed = await marketplace_installer.uninstall(kind, slug)
    except marketplace_installer.InstallError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="not installed")
    _invalidate_cache(kind)
    return Response(status_code=204)
