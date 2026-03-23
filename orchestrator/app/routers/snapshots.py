"""
Snapshots Router - Timeline API for Project Versioning

Provides API endpoints for:
- Listing project snapshots (Timeline UI)
- Creating manual snapshots (user-initiated save points)
- Restoring from specific snapshots (time travel)

All snapshot operations use Kubernetes VolumeSnapshots backed by AWS EBS CSI driver.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..config import get_settings
from ..database import get_db
from ..models import Project, User
from ..schemas import (
    RestoreSnapshotResponse,
    SnapshotCreate,
    SnapshotListResponse,
    SnapshotResponse,
)
from ..services.snapshot_manager import get_snapshot_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects/{project_id}/snapshots", tags=["snapshots"])


async def get_project_for_user(project_id: UUID, user: User, db: AsyncSession) -> Project:
    """Get a project and verify the user has access to it via RBAC."""
    from ..permissions import Permission, get_project_with_access

    project, _role = await get_project_with_access(
        db, str(project_id), user.id, Permission.SNAPSHOT_VIEW
    )
    return project


@router.get("/", response_model=SnapshotListResponse)
async def list_snapshots(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all snapshots for a project (Timeline API).

    Returns snapshots ordered by creation date (newest first).
    Maximum of 5 snapshots are kept per project.

    Used by the frontend Timeline panel to display project history
    and allow users to restore to previous states.
    """
    await get_project_for_user(project_id, current_user, db)

    snapshot_manager = get_snapshot_manager()
    settings = get_settings()

    snapshots = await snapshot_manager.get_project_snapshots(project_id, db)

    return SnapshotListResponse(
        snapshots=[
            SnapshotResponse(
                id=s.id,
                project_id=s.project_id,
                snapshot_name=s.snapshot_name,
                snapshot_type=s.snapshot_type,
                status=s.status,
                label=s.label,
                volume_size_bytes=s.volume_size_bytes,
                created_at=s.created_at,
                ready_at=s.ready_at,
            )
            for s in snapshots
        ],
        total_count=len(snapshots),
        max_snapshots=settings.k8s_max_snapshots_per_project,
    )


@router.post("/", response_model=SnapshotResponse, status_code=status.HTTP_201_CREATED)
async def create_manual_snapshot(
    project_id: UUID,
    request: SnapshotCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a manual snapshot of the current project state.

    This allows users to create save points they can restore to later.
    Manual snapshots are labeled differently in the Timeline UI.

    Note: The project must be in 'active' state (running) to create a snapshot.

    Returns immediately with status='pending'. The frontend should poll
    GET /snapshots/{id} or GET /snapshots/ to check when status becomes 'ready'.
    This is non-blocking to ensure the API remains responsive.
    """
    project = await get_project_for_user(project_id, current_user, db)

    if project.environment_status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot create snapshot: project is {project.environment_status}. "
            "Project must be active (running) to create a snapshot.",
        )

    snapshot_manager = get_snapshot_manager()

    snapshot, error = await snapshot_manager.create_snapshot(
        project_id=project_id,
        user_id=current_user.id,
        db=db,
        snapshot_type="manual",
        label=request.label or "Manual save",
    )

    if error:
        logger.error(f"[SNAPSHOTS] Failed to create manual snapshot: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create snapshot: {error}",
        )

    # Return immediately with pending status - non-blocking design
    # The snapshot will become 'ready' once EBS completes (typically < 60 seconds)
    # Frontend polls to check status
    logger.info(f"[SNAPSHOTS] Created manual snapshot {snapshot.id} (status: pending)")

    return SnapshotResponse(
        id=snapshot.id,
        project_id=snapshot.project_id,
        snapshot_name=snapshot.snapshot_name,
        snapshot_type=snapshot.snapshot_type,
        status=snapshot.status,
        label=snapshot.label,
        volume_size_bytes=snapshot.volume_size_bytes,
        created_at=snapshot.created_at,
        ready_at=snapshot.ready_at,
    )


@router.get("/{snapshot_id}", response_model=SnapshotResponse)
async def get_snapshot(
    project_id: UUID,
    snapshot_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get details of a specific snapshot."""
    await get_project_for_user(project_id, current_user, db)

    from ..models import ProjectSnapshot

    snapshot = await db.get(ProjectSnapshot, snapshot_id)

    if not snapshot or snapshot.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Snapshot {snapshot_id} not found for project {project_id}",
        )

    return SnapshotResponse(
        id=snapshot.id,
        project_id=snapshot.project_id,
        snapshot_name=snapshot.snapshot_name,
        snapshot_type=snapshot.snapshot_type,
        status=snapshot.status,
        label=snapshot.label,
        volume_size_bytes=snapshot.volume_size_bytes,
        created_at=snapshot.created_at,
        ready_at=snapshot.ready_at,
    )


@router.post("/{snapshot_id}/restore", response_model=RestoreSnapshotResponse)
async def restore_snapshot(
    project_id: UUID,
    snapshot_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Restore a project to a specific snapshot point in time.

    WARNING: This will replace the current project state with the snapshot state.
    The current state is NOT automatically saved before restore - if you want to
    keep the current state, create a manual snapshot first.

    The project must be stopped (hibernated) before restoring.
    After restore, the project will need to be started again.
    """
    project = await get_project_for_user(project_id, current_user, db)

    # Verify snapshot exists and belongs to project
    from ..models import ProjectSnapshot

    snapshot = await db.get(ProjectSnapshot, snapshot_id)

    if not snapshot or snapshot.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Snapshot {snapshot_id} not found for project {project_id}",
        )

    if snapshot.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot restore from snapshot: status is {snapshot.status}. "
            "Only 'ready' snapshots can be restored.",
        )

    # Project must be hibernated to restore
    if project.environment_status not in ["hibernated", "stopped"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot restore: project is {project.environment_status}. "
            "Stop the project first before restoring from a snapshot.",
        )

    # Update project to point to this snapshot for next restore
    project.latest_snapshot_id = snapshot_id
    await db.commit()

    logger.info(
        f"[SNAPSHOTS] Set project {project_id} to restore from snapshot {snapshot.snapshot_name}"
    )

    return RestoreSnapshotResponse(
        success=True,
        message=f"Project will restore from '{snapshot.label or snapshot.snapshot_name}' on next start",
        snapshot_id=snapshot_id,
        restored_from=snapshot.snapshot_name,
    )
