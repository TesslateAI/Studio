"""
Design view endpoints.

- ``POST /api/projects/{slug}/design/index``
    Scan all JSX/TSX source files, inject stable ``data-oid`` attributes,
    persist the modified files back to the project volume, and return the
    oid → metadata index. Idempotent — already-indexed elements keep their
    oids and only newly-seen elements get fresh ones.

- ``GET /api/projects/{slug}/design/index``
    Return the cached index from ``.tesslate/design-index.json``.

- ``POST /api/projects/{slug}/design/apply-diff``
    Apply a list of ``CodeDiffRequest`` objects to the project source.
    Each request targets a specific ``oid`` and carries attribute/text/
    structure changes. The server resolves oids to files via the index,
    batches the requests per file, runs the Node AST worker, and writes
    the result back.

All AST work happens in a long-lived Node sidecar managed by
``orchestrator.app.services.design.ast_worker``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_unified import get_authenticated_user
from ..database import get_db
from ..models import User
from ..permissions import Permission
from ..services.design.ast_worker import AstWorkerError, get_ast_worker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_slug}/design", tags=["design"])


# JSX/TSX extensions we inject oids into. We only touch files that a
# React/Vite/Next.js project would actually render as components.
_SOURCE_EXTENSIONS = (".tsx", ".jsx")

# Directories we never scan — they contain generated code, deps, or
# build output that should not have oids injected into them.
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


def _is_source_file(path: str) -> bool:
    if not path.endswith(_SOURCE_EXTENSIONS):
        return False
    parts = path.split("/")
    return not any(part in _SKIP_DIR_SEGMENTS for part in parts)


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
    elements keep their ids."""
    # Local imports to avoid circular-import issues with routers/projects.py.
    from ..services.orchestration import get_orchestrator
    from .projects import get_project_by_slug

    project = await get_project_by_slug(
        db, project_slug, current_user, Permission.FILE_WRITE
    )
    orchestrator = get_orchestrator()

    # Enumerate candidate files
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

    source_paths = [
        e["path"]
        for e in tree
        if not e.get("is_dir") and _is_source_file(e["path"])
    ]
    if not source_paths:
        await _write_index(orchestrator, current_user.id, project.id, {})
        return {"index": {}, "file_count": 0, "modified_count": 0, "errors": []}

    # Read contents
    files_data, read_errors = await orchestrator.read_files_batch(
        user_id=current_user.id,
        project_id=project.id,
        container_name=None,
        paths=source_paths,
        subdir=None,
    )
    files_payload = [
        {"path": f["path"], "content": f["content"]} for f in files_data
    ]

    # Run the Node worker
    try:
        result = await get_ast_worker().index(files_payload)
    except AstWorkerError as exc:
        logger.error("[design.index] worker error: %s", exc)
        raise HTTPException(status_code=503, detail=f"AST worker error: {exc}") from exc

    # Persist modified files
    modified = 0
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
            modified += 1

    index_entries = result.get("index", {}) or {}
    await _write_index(orchestrator, current_user.id, project.id, index_entries)

    return {
        "index": index_entries,
        "file_count": len(source_paths),
        "modified_count": modified,
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

    project = await get_project_by_slug(
        db, project_slug, current_user, Permission.FILE_WRITE
    )
    orchestrator = get_orchestrator()

    requests: list[dict[str, Any]] = body.get("requests") or []
    if not requests:
        return {"modified": [], "unknown_oids": [], "errors": []}

    index_entries = await _read_index(orchestrator, current_user.id, project.id)
    if not index_entries:
        raise HTTPException(
            status_code=409,
            detail="design index is empty — run POST /design/index first",
        )

    # Group requests by file path
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
    files_payload = [
        {"path": f["path"], "content": f["content"]} for f in files_data
    ]

    # Run the worker
    try:
        result = await get_ast_worker().apply_diff(files_payload, requests)
    except AstWorkerError as exc:
        logger.error("[design.apply_diff] worker error: %s", exc)
        raise HTTPException(status_code=503, detail=f"AST worker error: {exc}") from exc

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

    return {
        "modified": modified_paths,
        "unknown_oids": unknown_oids,
        "read_errors": read_errors or [],
        "file_errors": file_errors,
    }
