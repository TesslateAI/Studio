"""
Project sync (local ↔ cloud) endpoints.

- `POST /api/v1/projects/sync/push`          — multipart zip + manifest
- `GET  /api/v1/projects/sync/pull/{id}`     — streamed zip
- `GET  /api/v1/projects/sync/manifest/{id}` — current cloud-side manifest
- `GET  /api/v1/projects/sync/history/{id}`  — list sync snapshots

Backed by `services.public.sync_service`. Conflict detection compares the
incoming file hashes against the most recent sync `ProjectSnapshot`; divergent
paths are returned in the response and the client must resolve before pushing
again. Never auto-overwrites.

Paid gates, size caps (413 before buffering full), heavy rate limits
(`rate_cost=10, rate_capacity=30`), and audit entries on every write.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import ProjectSnapshot, User
from ...permissions import Permission, get_project_with_access
from ...services.public.sync_service import (
    compute_blob_key,
    detect_conflicts,
    get_sync_storage,
)
from ._deps import audit_write, scoped
from ._shared import add_cache_headers, paginated_response

logger = logging.getLogger(__name__)

REQUIRED_SCOPE = Permission.PROJECTS_SYNC

MAX_PUSH_BYTES = 256 * 1024 * 1024  # 256 MB cap on sync zips

router = APIRouter(prefix="/api/v1/projects/sync", tags=["public-projects-sync"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PushResponse(BaseModel):
    snapshot_id: UUID
    blob_key: str
    size_bytes: int
    conflicts: list[dict]
    created: bool


class ManifestResponse(BaseModel):
    project_id: UUID
    snapshot_id: UUID | None
    manifest: dict
    updated_at: str | None


class SnapshotDict(BaseModel):
    id: UUID
    label: str | None
    size_bytes: int | None
    created_at: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _latest_sync_snapshot(db: AsyncSession, project_id: UUID) -> ProjectSnapshot | None:
    stmt = (
        select(ProjectSnapshot)
        .where(
            ProjectSnapshot.project_id == project_id,
            ProjectSnapshot.snapshot_type == "sync",
        )
        .order_by(ProjectSnapshot.created_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def _parse_manifest(raw: str) -> dict[str, str]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="manifest must be valid JSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="manifest must be an object")
    for k, v in data.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise HTTPException(status_code=400, detail="manifest entries must be string→string")
    return data


async def _read_capped(file: UploadFile, cap: int) -> bytes:
    """Read the uploaded file, rejecting with 413 if it exceeds cap."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > cap:
            raise HTTPException(
                status_code=413,
                detail=f"Sync zip exceeds {cap} bytes cap",
            )
        chunks.append(chunk)
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# POST /push
# ---------------------------------------------------------------------------


@router.post("/push", response_model=PushResponse)
async def push(
    project_id: UUID = Form(...),
    manifest: str = Form(...),
    label: str | None = Form(default=None),
    zip_file: UploadFile = File(...),
    user: User = Depends(scoped(Permission.PROJECTS_SYNC, rate_cost=10, rate_capacity=30)),
    db: AsyncSession = Depends(get_db),
) -> PushResponse:
    project, _role = await get_project_with_access(
        db, str(project_id), user.id, Permission.PROJECT_EDIT
    )

    incoming = _parse_manifest(manifest)

    current = await _latest_sync_snapshot(db, project.id)
    cloud_manifest = (current.sync_manifest or {}) if current else {}
    conflicts = detect_conflicts(incoming, cloud_manifest)
    if conflicts:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Sync conflicts detected; resolve locally before pushing again.",
                "latest_snapshot_id": str(current.id) if current else None,
                "conflicts": conflicts,
            },
        )

    data = await _read_capped(zip_file, MAX_PUSH_BYTES)
    blob_key = compute_blob_key(data)

    storage = get_sync_storage()
    await storage.put(blob_key, data)

    snapshot = ProjectSnapshot(
        project_id=project.id,
        user_id=user.id,
        snapshot_name=f"sync-{blob_key[:12]}",
        snapshot_namespace="sync",
        snapshot_type="sync",
        status="ready",
        label=label,
        sync_manifest=incoming,
        sync_blob_key=blob_key,
        sync_size_bytes=len(data),
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)

    await audit_write(
        db=db,
        user=user,
        action="project_sync.push",
        resource_type="project_snapshot",
        resource_id=snapshot.id,
        project_id=project.id,
        details={"size_bytes": len(data), "files": len(incoming)},
    )

    return PushResponse(
        snapshot_id=snapshot.id,
        blob_key=blob_key,
        size_bytes=len(data),
        conflicts=[],
        created=True,
    )


# ---------------------------------------------------------------------------
# GET /pull/{snapshot_id}
# ---------------------------------------------------------------------------


@router.get("/pull/{snapshot_id}")
async def pull(
    snapshot_id: UUID,
    user: User = Depends(scoped(Permission.PROJECTS_SYNC)),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    snapshot = (
        await db.execute(
            select(ProjectSnapshot).where(
                ProjectSnapshot.id == snapshot_id,
                ProjectSnapshot.snapshot_type == "sync",
            )
        )
    ).scalar_one_or_none()
    if snapshot is None or snapshot.sync_blob_key is None:
        raise HTTPException(status_code=404, detail="Sync snapshot not found")

    # Verify project access (view is sufficient for pull)
    await get_project_with_access(
        db, str(snapshot.project_id), user.id, Permission.PROJECT_VIEW
    )

    storage = get_sync_storage()
    try:
        data = await storage.get(snapshot.sync_blob_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Blob missing from storage") from exc

    async def _iter():
        chunk_size = 64 * 1024
        for i in range(0, len(data), chunk_size):
            yield data[i : i + chunk_size]

    return StreamingResponse(
        _iter(),
        media_type="application/zip",
        headers={
            "Content-Length": str(len(data)),
            "Content-Disposition": f'attachment; filename="sync-{snapshot_id}.zip"',
        },
    )


# ---------------------------------------------------------------------------
# GET /manifest/{project_id}
# ---------------------------------------------------------------------------


@router.get("/manifest/{project_id}", response_model=ManifestResponse)
async def manifest(
    project_id: UUID,
    response: Response,
    user: User = Depends(scoped(Permission.PROJECTS_SYNC)),
    db: AsyncSession = Depends(get_db),
) -> ManifestResponse:
    project, _role = await get_project_with_access(
        db, str(project_id), user.id, Permission.PROJECT_VIEW
    )
    current = await _latest_sync_snapshot(db, project.id)

    manifest_payload: dict[str, Any] = current.sync_manifest if current and current.sync_manifest else {}
    updated_at = current.created_at.isoformat() if current and current.created_at else None

    add_cache_headers(
        response,
        etag_source=f"sync-manifest:{project.id}:{current.id if current else 'none'}",
        max_age=10,
    )
    return ManifestResponse(
        project_id=project.id,
        snapshot_id=current.id if current else None,
        manifest=manifest_payload,
        updated_at=updated_at,
    )


# ---------------------------------------------------------------------------
# GET /history/{project_id}
# ---------------------------------------------------------------------------


@router.get("/history/{project_id}")
async def history(
    project_id: UUID,
    response: Response,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(scoped(Permission.PROJECTS_SYNC)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    project, _role = await get_project_with_access(
        db, str(project_id), user.id, Permission.PROJECT_VIEW
    )

    base_stmt = select(ProjectSnapshot).where(
        ProjectSnapshot.project_id == project.id,
        ProjectSnapshot.snapshot_type == "sync",
    )
    from sqlalchemy import func as sa_func

    total = (
        await db.execute(
            select(sa_func.count(ProjectSnapshot.id)).where(
                ProjectSnapshot.project_id == project.id,
                ProjectSnapshot.snapshot_type == "sync",
            )
        )
    ).scalar_one() or 0

    rows = (
        await db.execute(
            base_stmt.order_by(ProjectSnapshot.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
    ).scalars().all()

    items = [
        {
            "id": str(r.id),
            "label": r.label,
            "size_bytes": r.sync_size_bytes,
            "blob_key": r.sync_blob_key,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]

    add_cache_headers(response, etag_source=f"sync-history:{project.id}:{total}:{page}", max_age=10)
    return paginated_response(items, total, page, limit)
