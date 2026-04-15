"""Project import and sync (push/pull/status) endpoints."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import User
from ...services import sync_client
from ...services.cloud_client import CircuitOpenError, NotPairedError
from ...users import current_active_user
from ._helpers import _map_sync_error

logger = logging.getLogger(__name__)

router = APIRouter()


class DesktopImportBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    path: str = Field(..., min_length=1)
    runtime: str | None = None


@router.post("/import")
async def desktop_import_project(
    body: DesktopImportBody,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a project from an existing on-disk directory."""
    from ...schemas import Project as ProjectSchema
    from ...schemas import ProjectCreate
    from ..projects import create_project_from_payload

    if body.runtime is not None and body.runtime not in {"local", "docker", "k8s"}:
        raise HTTPException(status_code=400, detail="runtime must be one of: local, docker, k8s")

    payload = ProjectCreate(
        name=body.name,
        source_type="base",
        import_path=body.path,
        runtime=body.runtime,
    )
    result = await create_project_from_payload(payload, current_user=user, db=db)
    return {"project": ProjectSchema.model_validate(result["project"]).model_dump(mode="json")}


@router.post("/projects/{project_id}/sync/push")
async def sync_push(
    project_id: uuid.UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from . import _load_project

    project = await _load_project(project_id, user, db)
    try:
        result = await sync_client.push(project, db=db)
    except (
        NotPairedError,
        sync_client.ConflictError,
        CircuitOpenError,
        sync_client.SyncError,
    ) as exc:
        raise _map_sync_error(exc) from exc
    return {
        "sync_id": result.sync_id,
        "uploaded_at": result.uploaded_at,
        "bytes_uploaded": result.bytes_uploaded,
    }


@router.post("/projects/{project_id}/sync/pull")
async def sync_pull(
    project_id: uuid.UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from . import _load_project

    project = await _load_project(project_id, user, db)
    try:
        result = await sync_client.pull(str(project_id), project=project)
    except (
        NotPairedError,
        sync_client.ConflictError,
        CircuitOpenError,
        sync_client.SyncError,
    ) as exc:
        raise _map_sync_error(exc) from exc
    return {
        "project_id": result.project_id,
        "files_written": result.files_written,
        "bytes_downloaded": result.bytes_downloaded,
    }


@router.get("/projects/{project_id}/sync/status")
async def sync_status(
    project_id: uuid.UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from . import _load_project

    project = await _load_project(project_id, user, db)
    local_last = project.last_sync_at.isoformat() if project.last_sync_at else None
    cloud_updated_at: str | None = None
    degraded = False
    try:
        from ...services.cloud_client import get_cloud_client

        client = await get_cloud_client()
        remote = await sync_client._get_remote_manifest(client, str(project_id))
        if remote is not None:
            cloud_updated_at = remote.get("updated_at")
    except (NotPairedError, CircuitOpenError, sync_client.SyncError) as exc:
        logger.debug("sync_status: cloud unavailable, degrading (%s)", exc)
        degraded = True

    in_sync = False
    if local_last and cloud_updated_at:
        remote_dt = sync_client._parse_updated_at(cloud_updated_at)
        local_dt = project.last_sync_at
        if local_dt is not None and local_dt.tzinfo is None:
            local_dt = local_dt.replace(tzinfo=UTC)
        if remote_dt is not None and local_dt is not None:
            in_sync = not (remote_dt > local_dt)
    elif not cloud_updated_at and not local_last:
        in_sync = True

    return {
        "last_sync_at": local_last,
        "cloud_updated_at": cloud_updated_at,
        "in_sync": in_sync,
        "degraded": degraded,
    }
