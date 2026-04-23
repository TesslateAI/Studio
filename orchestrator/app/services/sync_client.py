"""
Desktop ↔ cloud project sync client.

Drives the bidirectional project sync flow on the desktop shell:

  1. **pack_project(project)** — zips the on-disk project root (from
     ``_get_project_root`` or ``source_path``) into a tmp ``.zip`` on disk.
     Streams via ``ZipFile`` so large projects don't balloon memory.
  2. **compute_manifest(project)** — walks the filtered tree and produces
     ``{project_id, files:[{path, sha256, size}], total_size, created_at}``.
     SHA-256 is computed per-file; manifest is stable/deterministic.
  3. **push(project)** — cloud manifest pre-flight for conflict detection,
     multipart upload of zip + manifest, updates ``Project.last_sync_at``.
  4. **pull(project_id)** — streams cloud zip via a bearer-LESS dedicated
     ``httpx.AsyncClient`` (signed URLs are cross-origin) into an
     ``.incoming/`` staging dir, then atomically swaps with the current
     project tree (the old tree moves to ``.replaced/`` and is deleted on
     success; restored on failure).

All failures surface as :class:`SyncError` or :class:`ConflictError` with a
human-readable reason so the router can map to a clean 4xx/5xx. Transport
errors NEVER escape as bare ``httpx`` exceptions.

Excludes (hard-coded, mirrors local.py orchestration conventions):
  ``.tesslate/logs``, ``node_modules``, ``__pycache__``, ``.venv``, ``venv``,
  ``.git``, ``dist``, ``build``, ``.next``, ``.mypy_cache``, ``.pytest_cache``,
  ``.ruff_cache``, ``target``

``.git`` is excluded wholesale — simpler and safer than selectively keeping
``HEAD``/``refs``; branch info can be rebuilt from cloud-side metadata.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Project
from .cloud_client import (
    CircuitOpenError,
    CloudClient,
    NotPairedError,
    get_cloud_client,
)
from .desktop_paths import resolve_opensail_home

logger = logging.getLogger(__name__)


EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".git",
        "dist",
        "build",
        ".next",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "target",
    }
)
EXCLUDED_PATH_PREFIXES: tuple[str, ...] = (".tesslate/logs",)

_DOWNLOAD_TIMEOUT = httpx.Timeout(120.0)
_STREAM_CHUNK = 64 * 1024


class SyncError(Exception):
    """Domain error raised by any sync operation."""


class ConflictError(SyncError):
    """Remote has a newer manifest than local — pull (or force) first."""

    def __init__(self, message: str, *, cloud_updated_at: str | None = None) -> None:
        super().__init__(message)
        self.cloud_updated_at = cloud_updated_at


@dataclass(frozen=True)
class PushResult:
    sync_id: str
    uploaded_at: str
    bytes_uploaded: int


@dataclass(frozen=True)
class PullResult:
    project_id: str
    files_written: int
    bytes_downloaded: int


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _project_root(project: Any) -> Path:
    """Resolve the on-disk root for a Project row.

    Prefers ``project.source_path`` (imported projects pointing at an external
    directory) over the orchestration-managed root.
    """
    source = getattr(project, "source_path", None)
    if source:
        return Path(source).expanduser().resolve()
    # Fall back to the local orchestrator's resolution (desktop home vs $PROJECT_ROOT).
    from .orchestration.local import _get_project_root

    return _get_project_root(project)


def _is_excluded(rel: Path) -> bool:
    parts = rel.parts
    if any(p in EXCLUDED_DIRS for p in parts):
        return True
    rel_str = rel.as_posix()
    return any(rel_str.startswith(pref) for pref in EXCLUDED_PATH_PREFIXES)


def _iter_included_files(root: Path):
    """Yield (abs_path, rel_posix) for every file under ``root`` that passes
    the exclusion filter. Deterministic sort order so manifests are stable.
    """
    if not root.exists():
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _is_excluded(rel):
            continue
        yield path, rel.as_posix()


# ---------------------------------------------------------------------------
# Pack + manifest
# ---------------------------------------------------------------------------


async def pack_project(project: Any) -> Path:
    """Create a tmp ``.zip`` of the filtered project tree. Returns its Path."""
    root = _project_root(project)
    if not root.exists():
        raise SyncError(f"project root does not exist: {root}")

    fd, tmp_name = tempfile.mkstemp(prefix="tesslate-sync-", suffix=".zip")
    # Close the fd — ZipFile opens its own handle.
    import os as _os

    _os.close(fd)
    tmp = Path(tmp_name)

    def _build() -> None:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for abs_path, rel in _iter_included_files(root):
                zf.write(abs_path, arcname=rel)

    try:
        await asyncio.to_thread(_build)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise SyncError(f"failed to pack project: {exc}") from exc
    return tmp


async def compute_manifest(project: Any) -> dict[str, Any]:
    """Walk the filtered project tree and return a stable manifest dict."""
    root = _project_root(project)
    if not root.exists():
        raise SyncError(f"project root does not exist: {root}")

    def _build() -> dict[str, Any]:
        files: list[dict[str, Any]] = []
        total = 0
        for abs_path, rel in _iter_included_files(root):
            h = hashlib.sha256()
            size = 0
            with abs_path.open("rb") as fh:
                while True:
                    chunk = fh.read(_STREAM_CHUNK)
                    if not chunk:
                        break
                    h.update(chunk)
                    size += len(chunk)
            files.append({"path": rel, "sha256": h.hexdigest(), "size": size})
            total += size
        return {
            "project_id": str(getattr(project, "id", "") or ""),
            "files": files,
            "total_size": total,
            "created_at": datetime.now(UTC).isoformat(),
        }

    return await asyncio.to_thread(_build)


# ---------------------------------------------------------------------------
# Push
# ---------------------------------------------------------------------------


def _parse_updated_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # isoformat with or without trailing Z
        cleaned = value.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


async def _get_remote_manifest(client: CloudClient, project_id: str) -> dict[str, Any] | None:
    """Fetch the cloud manifest; return None if the project has no cloud history."""
    try:
        resp = await client.get(f"/api/v1/projects/sync/manifest/{project_id}")
    except NotPairedError:
        raise
    except CircuitOpenError:
        raise
    except (httpx.TransportError, httpx.TimeoutException) as exc:
        raise SyncError(f"cloud transport error: {exc}") from exc

    if resp.status_code == 404:
        return None
    if resp.status_code >= 400:
        raise SyncError(f"cloud manifest fetch failed: HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise SyncError(f"cloud returned non-JSON manifest: {exc}") from exc


async def push(
    project: Any,
    *,
    db: AsyncSession | None = None,
) -> PushResult:
    """Upload the local project tree to the cloud after a manifest pre-flight.

    Raises:
        ConflictError: remote manifest is newer than ``project.last_sync_at``.
        SyncError: any other failure (transport, 4xx/5xx, disk, etc.).
        NotPairedError: no cloud token — desktop must pair first.
    """
    project_id = str(project.id)
    client = await get_cloud_client()

    remote = await _get_remote_manifest(client, project_id)
    if remote is not None:
        remote_updated = _parse_updated_at(remote.get("updated_at"))
        local_last_sync = getattr(project, "last_sync_at", None)
        if remote_updated is not None and local_last_sync is not None:
            # Both sides aware-datetime; compare directly.
            if local_last_sync.tzinfo is None:
                local_last_sync = local_last_sync.replace(tzinfo=UTC)
            if remote_updated > local_last_sync:
                raise ConflictError(
                    "cloud has a newer sync; pull or force before pushing",
                    cloud_updated_at=remote.get("updated_at"),
                )
        elif remote_updated is not None and local_last_sync is None:
            raise ConflictError(
                "cloud has a sync but local has never pushed; pull or force",
                cloud_updated_at=remote.get("updated_at"),
            )

    manifest = await compute_manifest(project)
    zip_path = await pack_project(project)
    try:
        import json as _json

        bytes_uploaded = zip_path.stat().st_size
        with zip_path.open("rb") as fh:
            files = {"zip_file": ("project.zip", fh, "application/zip")}
            data = {
                "project_id": project_id,
                "manifest": _json.dumps(manifest),
            }
            try:
                resp = await client.post_multipart(
                    "/api/v1/projects/sync/push",
                    files=files,
                    data=data,
                )
            except NotPairedError:
                raise
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                raise SyncError(f"cloud transport error during push: {exc}") from exc
    finally:
        zip_path.unlink(missing_ok=True)

    if resp.status_code == 409:
        try:
            body = resp.json()
        except ValueError:
            body = {}
        raise ConflictError(
            "cloud reported sync conflicts; resolve and retry",
            cloud_updated_at=str(body.get("latest_snapshot_id") or ""),
        )
    if resp.status_code >= 400:
        raise SyncError(f"cloud push failed: HTTP {resp.status_code}")

    try:
        body = resp.json()
    except ValueError as exc:
        raise SyncError(f"cloud returned non-JSON push response: {exc}") from exc

    sync_id = str(body.get("sync_id") or body.get("snapshot_id") or "")
    uploaded_at = str(
        body.get("uploaded_at") or body.get("created_at") or datetime.now(UTC).isoformat()
    )
    if not sync_id:
        raise SyncError("cloud push response missing sync_id")

    now = datetime.now(UTC)
    # Update in-memory attr so callers see the new timestamp; best-effort DB update.
    with contextlib.suppress(Exception):
        project.last_sync_at = now  # type: ignore[attr-defined]
    if db is not None:
        await db.execute(
            sa_update(Project).where(Project.id == project.id).values(last_sync_at=now)
        )
        await db.commit()

    return PushResult(
        sync_id=sync_id,
        uploaded_at=uploaded_at,
        bytes_uploaded=bytes_uploaded,
    )


# ---------------------------------------------------------------------------
# Pull
# ---------------------------------------------------------------------------


def _destination_for_pull(project: Any | None, project_id: str) -> Path:
    """Resolve the extraction destination for a pull.

    If ``project`` is provided, reuses :func:`_project_root`. Otherwise falls
    back to ``$OPENSAIL_HOME/projects/{project_id}``.
    """
    if project is not None:
        return _project_root(project)
    return resolve_opensail_home() / "projects" / project_id


async def _download_zip(url_or_path: str, *, base_url: str | None = None) -> Path:
    """Stream a zip to a tmp file using a bearer-LESS httpx client.

    ``url_or_path`` may be a full URL (signed cross-origin) or a path on the
    cloud host. When it's a path, callers must pass ``base_url``.
    """
    target = url_or_path
    if target.startswith("/") and base_url:
        target = base_url.rstrip("/") + target

    fd, tmp_name = tempfile.mkstemp(prefix="tesslate-pull-", suffix=".zip")
    import os as _os

    _os.close(fd)
    tmp = Path(tmp_name)

    try:
        async with (
            httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT) as http,
            http.stream("GET", target) as resp,
        ):
            if resp.status_code >= 400:
                raise SyncError(f"cloud pull failed: HTTP {resp.status_code}")
            with tmp.open("wb") as fh:
                async for chunk in resp.aiter_bytes(_STREAM_CHUNK):
                    if chunk:
                        fh.write(chunk)
    except SyncError:
        tmp.unlink(missing_ok=True)
        raise
    except (httpx.TransportError, httpx.TimeoutException) as exc:
        tmp.unlink(missing_ok=True)
        raise SyncError(f"cloud transport error during pull: {exc}") from exc
    return tmp


def _extract_atomic(zip_path: Path, dest: Path) -> tuple[int, int]:
    """Atomically replace ``dest`` with the contents of ``zip_path``.

    Strategy:
      - Extract to ``dest.with_suffix('.incoming')``.
      - If ``dest`` already exists, move it to ``dest.with_suffix('.replaced')``.
      - Rename incoming → dest.
      - On any failure: incoming is removed; original is restored from
        ``.replaced``. On success, ``.replaced`` is deleted.

    Returns ``(files_written, bytes_downloaded)``.
    """
    incoming = (
        dest.with_suffix(dest.suffix + ".incoming")
        if dest.suffix
        else dest.parent / (dest.name + ".incoming")
    )
    replaced = (
        dest.with_suffix(dest.suffix + ".replaced")
        if dest.suffix
        else dest.parent / (dest.name + ".replaced")
    )

    # Clean any leftovers from a previous crashed run.
    if incoming.exists():
        shutil.rmtree(incoming, ignore_errors=True)
    if replaced.exists():
        shutil.rmtree(replaced, ignore_errors=True)

    dest.parent.mkdir(parents=True, exist_ok=True)
    incoming.mkdir(parents=True, exist_ok=False)

    files_written = 0
    bytes_written = 0
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                # Guard against path traversal.
                rel = Path(info.filename)
                if rel.is_absolute() or ".." in rel.parts:
                    raise SyncError(f"unsafe zip entry: {info.filename}")
                target = incoming / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src, target.open("wb") as dst:
                    while True:
                        chunk = src.read(_STREAM_CHUNK)
                        if not chunk:
                            break
                        dst.write(chunk)
                        bytes_written += len(chunk)
                files_written += 1

        moved_original = False
        if dest.exists():
            dest.rename(replaced)
            moved_original = True
        try:
            incoming.rename(dest)
        except OSError:
            # Roll back: restore original.
            if moved_original and replaced.exists():
                replaced.rename(dest)
            raise
        if moved_original:
            shutil.rmtree(replaced, ignore_errors=True)
    except Exception:
        shutil.rmtree(incoming, ignore_errors=True)
        # If we'd moved original aside but failed before re-renaming, put it back.
        if replaced.exists() and not dest.exists():
            replaced.rename(dest)
        raise

    return files_written, bytes_written


async def pull(
    project_id: str,
    *,
    project: Any | None = None,
) -> PullResult:
    """Fetch the latest cloud sync for ``project_id`` and extract atomically."""
    client = await get_cloud_client()
    path = f"/api/v1/projects/sync/pull/{project_id}"
    try:
        resp = await client.get(path)
    except NotPairedError:
        raise
    except (httpx.TransportError, httpx.TimeoutException) as exc:
        raise SyncError(f"cloud transport error during pull: {exc}") from exc

    if resp.status_code >= 400:
        raise SyncError(f"cloud pull failed: HTTP {resp.status_code}")

    # If the cloud returned a JSON redirect-to-signed-URL body, follow it.
    content_type = resp.headers.get("content-type", "")
    zip_path: Path
    if content_type.startswith("application/json"):
        try:
            body = resp.json()
        except ValueError as exc:
            raise SyncError(f"cloud pull returned malformed JSON: {exc}") from exc
        signed_url = body.get("download_url") or body.get("url")
        if not isinstance(signed_url, str) or not signed_url:
            raise SyncError("cloud pull JSON missing download_url")
        zip_path = await _download_zip(signed_url)
    else:
        # Direct zip in response body.
        fd, tmp_name = tempfile.mkstemp(prefix="tesslate-pull-", suffix=".zip")
        import os as _os

        _os.close(fd)
        zip_path = Path(tmp_name)
        zip_path.write_bytes(resp.content)

    dest = _destination_for_pull(project, project_id)
    try:
        files_written, bytes_written = await asyncio.to_thread(_extract_atomic, zip_path, dest)
    finally:
        zip_path.unlink(missing_ok=True)

    return PullResult(
        project_id=project_id,
        files_written=files_written,
        bytes_downloaded=bytes_written,
    )


# ---------------------------------------------------------------------------
# Singleton-ish accessor (the module itself is the client; this exists for
# symmetry with other services and to give tests a single patch-point).
# ---------------------------------------------------------------------------


class _SyncClient:
    """Facade exposing the module-level functions as methods."""

    pack_project = staticmethod(pack_project)
    compute_manifest = staticmethod(compute_manifest)
    push = staticmethod(push)
    pull = staticmethod(pull)


_singleton: _SyncClient | None = None


def get_sync_client() -> _SyncClient:
    global _singleton
    if _singleton is None:
        _singleton = _SyncClient()
    return _singleton
