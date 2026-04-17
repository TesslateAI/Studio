"""
Design view endpoints.

- ``POST /api/projects/{slug}/design/index``
    Scan all JSX/TSX source files, inject stable ``data-oid`` attributes,
    persist the modified files back to the project volume, and return the
    oid → metadata index. Idempotent — already-indexed elements keep their
    oids and only newly-seen elements get fresh ones. Uses an on-volume
    SHA skip-unchanged cache so unchanged files are never re-parsed.

- ``GET /api/projects/{slug}/design/index``
    Return the cached index from ``.tesslate/design-index.json``.

- ``POST /api/projects/{slug}/design/apply-diff``
    Apply a list of ``CodeDiffRequest`` objects to the project source.
    Each request targets a specific ``oid`` and carries attribute/text/
    structure changes. The server resolves oids to files via the index,
    batches the requests per file, calls the standalone ``tesslate-ast``
    gRPC service, and writes the result back.

All AST work runs in a separate ``tesslate-ast`` Kubernetes service —
see ``orchestrator.app.services.design.ast_client``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_unified import get_authenticated_user
from ..config import get_settings
from ..database import get_db
from ..models import User
from ..permissions import Permission
from ..services.design.ast_client import (
    AstClientBudgetError,
    AstClientError,
    CircuitOpenError,
    get_ast_client,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_slug}/design", tags=["design"])


_SOURCE_EXTENSIONS = (".tsx", ".jsx")

_SKIP_DIR_SEGMENTS = {
    "node_modules",
    ".next",
    ".turbo",
    ".git",
    "dist",
    "build",
    "out",
    ".cache",
    ".vite",
    ".parcel-cache",
    "coverage",
    ".tesslate",
}

_INDEX_FILE = ".tesslate/design-index.json"
_INDEX_SCHEMA_VERSION = 1
_HASHES_FILE = ".tesslate/design-hashes.json"
_HASHES_SCHEMA_VERSION = 1


def _is_source_file(path: str) -> bool:
    if not path.endswith(_SOURCE_EXTENSIONS):
        return False
    parts = path.split("/")
    return not any(part in _SKIP_DIR_SEGMENTS for part in parts)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ──────────────────────────────────────────────────────────────────────
# Index JSON (oid → metadata) — on-volume cache
# ──────────────────────────────────────────────────────────────────────
async def _read_index(orchestrator, user_id, project_id) -> dict[str, Any]:
    """Read the cached design index, returning an empty dict on any failure."""
    try:
        result = await orchestrator.read_file_content(
            user_id=user_id,
            project_id=project_id,
            container_name=None,
            file_path=_INDEX_FILE,
            subdir=None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[design] no cached index: %s", exc)
        return {}
    if result is None:
        return {}
    content = result["content"] if isinstance(result, dict) else result
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("[design] cached index is not valid JSON; ignoring")
        return {}
    if isinstance(data, dict) and isinstance(data.get("entries"), dict):
        return data["entries"]
    return {}


async def _write_index(orchestrator, user_id, project_id, entries: dict[str, Any]) -> None:
    payload = json.dumps(
        {"version": _INDEX_SCHEMA_VERSION, "entries": entries},
        indent=2,
        ensure_ascii=False,
    )
    await orchestrator.write_file(
        user_id=user_id,
        project_id=project_id,
        container_name=None,
        file_path=_INDEX_FILE,
        content=payload,
    )


# ──────────────────────────────────────────────────────────────────────
# Hashes JSON (path → {sha256, size, mtime}) — skip-unchanged cache
# ──────────────────────────────────────────────────────────────────────
async def _read_hashes(orchestrator, user_id, project_id) -> dict[str, dict[str, Any]]:
    try:
        result = await orchestrator.read_file_content(
            user_id=user_id,
            project_id=project_id,
            container_name=None,
            file_path=_HASHES_FILE,
            subdir=None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[design] no cached hashes: %s", exc)
        return {}
    if result is None:
        return {}
    content = result["content"] if isinstance(result, dict) else result
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("[design] cached hashes are not valid JSON; ignoring")
        return {}
    if isinstance(data, dict) and isinstance(data.get("entries"), dict):
        return data["entries"]
    return {}


async def _write_hashes(
    orchestrator, user_id, project_id, entries: dict[str, dict[str, Any]]
) -> None:
    payload = json.dumps(
        {"version": _HASHES_SCHEMA_VERSION, "entries": entries},
        indent=2,
        ensure_ascii=False,
    )
    await orchestrator.write_file(
        user_id=user_id,
        project_id=project_id,
        container_name=None,
        file_path=_HASHES_FILE,
        content=payload,
    )


def _ast_error_to_http(exc: Exception) -> HTTPException:
    """Map AST-client exceptions to HTTP responses that degrade gracefully."""
    if isinstance(exc, CircuitOpenError):
        return HTTPException(
            status_code=503,
            detail="design service temporarily unavailable",
            headers={"Retry-After": "30"},
        )
    if isinstance(exc, AstClientBudgetError):
        return HTTPException(
            status_code=413,
            detail=f"request too large for AST service: {exc}",
        )
    return HTTPException(
        status_code=503,
        detail=f"AST service error: {exc}",
        headers={"Retry-After": "5"},
    )


# ══════════════════════════════════════════════════════════════════════
# POST /index — inject oids and build the project index
# ══════════════════════════════════════════════════════════════════════
@router.post("/index")
async def index_project(
    project_slug: str,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Scan the project, inject ``data-oid`` into every JSX element, and
    return the oid → metadata mapping. Safe to re-run: already-oid'd
    elements keep their ids. Unchanged files (by sha256) are skipped and
    their previous index entries are preserved.
    """
    from ..services.orchestration import get_orchestrator
    from .projects import get_project_by_slug

    project = await get_project_by_slug(db, project_slug, current_user, Permission.FILE_WRITE)
    orchestrator = get_orchestrator()
    settings = get_settings()

    # Enumerate candidate files — tree includes size and mod_time per entry.
    try:
        tree = await orchestrator.list_tree(
            user_id=current_user.id,
            project_id=project.id,
            container_name=None,
            subdir=None,
        )
    except Exception as exc:
        logger.exception("[design.index] list_tree failed: %s", exc)
        raise HTTPException(status_code=500, detail="failed to list project files") from exc

    tree_by_path: dict[str, dict[str, Any]] = {
        e["path"]: e for e in tree if not e.get("is_dir") and _is_source_file(e["path"])
    }
    source_paths = list(tree_by_path.keys())
    if not source_paths:
        await _write_index(orchestrator, current_user.id, project.id, {})
        await _write_hashes(orchestrator, current_user.id, project.id, {})
        return {"index": {}, "file_count": 0, "modified_count": 0, "errors": []}

    # Load caches. If hash caching is disabled, treat as empty → every file is
    # sent to AST every time.
    hash_cache_enabled = settings.ast_service_hash_cache_enabled
    previous_hashes = (
        await _read_hashes(orchestrator, current_user.id, project.id) if hash_cache_enabled else {}
    )
    previous_index = await _read_index(orchestrator, current_user.id, project.id)

    # Partition into "can trust cached sha from (size, mtime)" vs "must read".
    paths_to_read: list[str] = []
    trusted_hashes: dict[str, str] = {}
    for path, tree_entry in tree_by_path.items():
        cached = previous_hashes.get(path) if hash_cache_enabled else None
        if (
            cached
            and cached.get("size") == tree_entry.get("size")
            and cached.get("mtime") == tree_entry.get("mod_time")
            and isinstance(cached.get("sha256"), str)
        ):
            trusted_hashes[path] = cached["sha256"]
        else:
            paths_to_read.append(path)

    # Read the files whose (size, mtime) didn't match cache.
    files_by_path: dict[str, str] = {}
    read_errors: list[str] = []
    if paths_to_read:
        files_data, read_errors = await orchestrator.read_files_batch(
            user_id=current_user.id,
            project_id=project.id,
            container_name=None,
            paths=paths_to_read,
            subdir=None,
        )
        for f in files_data:
            files_by_path[f["path"]] = f["content"]

    # Decide changed vs unchanged. A file is unchanged iff its fresh sha
    # matches previous_hashes. Trusted-cache files are unchanged by assumption.
    changed_files: list[dict[str, str]] = []
    fresh_hashes: dict[str, dict[str, Any]] = {}
    unchanged_paths: set[str] = set()
    for path, tree_entry in tree_by_path.items():
        if path in trusted_hashes:
            sha = trusted_hashes[path]
            unchanged_paths.add(path)
            fresh_hashes[path] = {
                "sha256": sha,
                "size": tree_entry.get("size", 0),
                "mtime": tree_entry.get("mod_time", 0),
            }
            continue
        content = files_by_path.get(path)
        if content is None:
            # Read failed — skip this file; it'll be retried next run.
            continue
        sha = _sha256(content)
        fresh_hashes[path] = {
            "sha256": sha,
            "size": tree_entry.get("size", 0),
            "mtime": tree_entry.get("mod_time", 0),
        }
        prev = previous_hashes.get(path) if hash_cache_enabled else None
        if prev and prev.get("sha256") == sha:
            unchanged_paths.add(path)
        else:
            changed_files.append({"path": path, "content": content})

    logger.info(
        "[design.index] total=%d unchanged=%d changed=%d",
        len(source_paths),
        len(unchanged_paths),
        len(changed_files),
    )

    # Preserve index entries whose path is in the unchanged set.
    preserved_index = {
        oid: meta
        for oid, meta in previous_index.items()
        if isinstance(meta, dict) and meta.get("path") in unchanged_paths
    }

    # Call AST only for changed files.
    file_errors: list[dict[str, str]] = []
    modified = 0
    new_index: dict[str, Any] = {}
    if changed_files:
        try:
            result = await get_ast_client().index(changed_files)
        except (AstClientError, CircuitOpenError, AstClientBudgetError) as exc:
            logger.error("[design.index] ast service error: %s", exc)
            raise _ast_error_to_http(exc) from exc

        for f in result.get("files", []):
            if f.get("error"):
                file_errors.append({"path": f["path"], "error": f["error"]})
                continue
            if not f.get("modified"):
                continue
            ok = await orchestrator.write_file(
                user_id=current_user.id,
                project_id=project.id,
                container_name=None,
                file_path=f["path"],
                content=f["content"],
            )
            if ok:
                modified += 1
                # The write changes the file content — refresh its hash so the
                # next request's skip-cache works. Size/mtime are refreshed on
                # the next list_tree anyway, but sha must be the new content's.
                fresh_hashes[f["path"]] = {
                    "sha256": _sha256(f["content"]),
                    "size": len(f["content"].encode("utf-8")),
                    "mtime": fresh_hashes.get(f["path"], {}).get("mtime", 0),
                }
        new_index = result.get("index", {}) or {}

    merged_index: dict[str, Any] = {**preserved_index, **new_index}

    await _write_index(orchestrator, current_user.id, project.id, merged_index)
    if hash_cache_enabled:
        await _write_hashes(orchestrator, current_user.id, project.id, fresh_hashes)

    return {
        "index": merged_index,
        "file_count": len(source_paths),
        "modified_count": modified,
        "unchanged_count": len(unchanged_paths),
        "read_errors": read_errors or [],
        "file_errors": file_errors,
    }


# ══════════════════════════════════════════════════════════════════════
# GET /index — return the cached index
# ══════════════════════════════════════════════════════════════════════
@router.get("/index")
async def get_design_index(
    project_slug: str,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from ..services.orchestration import get_orchestrator
    from .projects import get_project_by_slug

    project = await get_project_by_slug(db, project_slug, current_user)
    orchestrator = get_orchestrator()
    entries = await _read_index(orchestrator, current_user.id, project.id)
    return {"index": entries}


# ══════════════════════════════════════════════════════════════════════
# POST /apply-diff — apply a batch of CodeDiffRequests
# ══════════════════════════════════════════════════════════════════════
@router.post("/apply-diff")
async def apply_diff(
    project_slug: str,
    body: dict = Body(...),
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Body shape:
        {
            "requests": [
                {
                    "oid": "abc1234",
                    "attributes": {"className": "p-4 text-red-500"},
                    "override_classes": false,
                    "text_content": "Hello",
                    "structure_changes": [
                        {"type": "insert", "location": "append",
                         "element": {"tag_name": "span", "text": "x", "oid": "..."}}
                    ],
                    "remove": false
                }
            ]
        }
    """
    from ..services.orchestration import get_orchestrator
    from .projects import get_project_by_slug

    project = await get_project_by_slug(db, project_slug, current_user, Permission.FILE_WRITE)
    orchestrator = get_orchestrator()
    settings = get_settings()

    requests: list[dict[str, Any]] = body.get("requests") or []
    if not requests:
        return {"modified": [], "unknown_oids": [], "errors": []}

    index_entries = await _read_index(orchestrator, current_user.id, project.id)
    if not index_entries:
        raise HTTPException(
            status_code=409,
            detail="design index is empty — run POST /design/index first",
        )

    by_file: dict[str, list[dict[str, Any]]] = {}
    unknown_oids: list[str] = []
    for req in requests:
        oid = req.get("oid")
        meta = index_entries.get(oid) if oid else None
        if not meta:
            unknown_oids.append(oid or "<no-oid>")
            continue
        by_file.setdefault(meta["path"], []).append(req)

    if not by_file:
        return {"modified": [], "unknown_oids": unknown_oids, "errors": []}

    file_paths = list(by_file.keys())
    files_data, read_errors = await orchestrator.read_files_batch(
        user_id=current_user.id,
        project_id=project.id,
        container_name=None,
        paths=file_paths,
        subdir=None,
    )
    files_payload = [{"path": f["path"], "content": f["content"]} for f in files_data]

    try:
        result = await get_ast_client().apply_diff(files_payload, requests)
    except (AstClientError, CircuitOpenError, AstClientBudgetError) as exc:
        logger.error("[design.apply_diff] ast service error: %s", exc)
        raise _ast_error_to_http(exc) from exc

    # Refresh hashes for files AST actually modified so the skip-cache
    # stays consistent with what's on disk.
    updated_hashes: dict[str, dict[str, Any]] = {}
    modified_paths: list[str] = []
    file_errors: list[dict[str, str]] = []
    for f in result.get("files", []):
        if f.get("error"):
            file_errors.append({"path": f["path"], "error": f["error"]})
            continue
        if not f.get("modified"):
            continue
        ok = await orchestrator.write_file(
            user_id=current_user.id,
            project_id=project.id,
            container_name=None,
            file_path=f["path"],
            content=f["content"],
        )
        if ok:
            modified_paths.append(f["path"])
            updated_hashes[f["path"]] = {
                "sha256": _sha256(f["content"]),
                "size": len(f["content"].encode("utf-8")),
                # mtime stays None here — next list_tree will refresh it.
                # The (size, sha256) pair is enough to detect staleness on
                # the next /design/index run; if mtime drifts, the hash
                # still matches and we short-circuit correctly.
                "mtime": 0,
            }

    if modified_paths and settings.ast_service_hash_cache_enabled:
        existing = await _read_hashes(orchestrator, current_user.id, project.id)
        existing.update(updated_hashes)
        await _write_hashes(orchestrator, current_user.id, project.id, existing)

    return {
        "modified": modified_paths,
        "unknown_oids": unknown_oids,
        "read_errors": read_errors or [],
        "file_errors": file_errors,
    }
