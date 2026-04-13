"""
Snapshots Router — CAS Snapshot API for Project Timeline

All snapshots are CAS-based (content-addressable, stored in S3 via the btrfs CSI
sync daemon). K8s VolumeSnapshots are NOT used — the Hub manages everything.

Provides:
- List CAS checkpoint snapshots for a project
- Create a manual checkpoint
- Restore to a specific checkpoint (by CAS hash)
"""

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_unified import get_authenticated_user
from ..database import get_db
from ..models import Project, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects/{project_id}/snapshots", tags=["snapshots"])


# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------


class CASSnapshot(BaseModel):
    hash: str
    role: str  # "checkpoint"
    label: str
    ts: str  # ISO timestamp


class CASSnapshotListResponse(BaseModel):
    snapshots: list[CASSnapshot]
    volume_id: str


class TimelineSnapshot(BaseModel):
    hash: str
    parent: str
    prev: str  # chronologically previous snapshot (unlike parent which skips for consolidations)
    role: str
    label: str
    ts: str
    consolidation: bool = False


class TimelineBranch(BaseModel):
    name: str
    display_name: str
    hash: str  # tip hash this branch points to
    is_current: bool
    checkpoint_count: int


class TimelineGraphResponse(BaseModel):
    head: str
    branches: list[TimelineBranch]
    snapshots: list[TimelineSnapshot]


class CreateBranchRequest(BaseModel):
    name: str


class CreateBranchResponse(BaseModel):
    name: str
    display_name: str


class CASSnapshotCreateRequest(BaseModel):
    label: str = ""


class CASSnapshotCreateResponse(BaseModel):
    hash: str
    label: str
    volume_id: str


class CASSnapshotRestoreResponse(BaseModel):
    success: bool
    message: str
    restored_hash: str
    node: str


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


async def _get_project(project_id: UUID, user: User, db: AsyncSession) -> Project:
    """Get a project and verify the user has access to it via RBAC."""
    from ..permissions import Permission, get_project_with_access

    project, _role = await get_project_with_access(
        db, str(project_id), user.id, Permission.SNAPSHOT_VIEW
    )
    return project


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@router.get("/", response_model=CASSnapshotListResponse)
async def list_snapshots(
    project_id: UUID,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """List CAS checkpoint snapshots for a project (Timeline API)."""
    project = await _get_project(project_id, current_user, db)

    from ..services.volume_manager import get_volume_manager

    vm = get_volume_manager()
    raw = await vm.list_snapshots(project.volume_id)

    snapshots = [
        CASSnapshot(
            hash=s.get("hash", ""),
            role=s.get("role", "checkpoint"),
            label=s.get("label", ""),
            ts=s.get("ts", ""),
        )
        for s in raw
    ]

    return CASSnapshotListResponse(snapshots=snapshots, volume_id=project.volume_id)


@router.get("/graph", response_model=TimelineGraphResponse)
async def get_timeline_graph(
    project_id: UUID,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the full manifest DAG for the project timeline UI.

    Includes all checkpoint snapshots (with parent references), HEAD,
    and branch pointers with user-friendly display names.
    """
    project = await _get_project(project_id, current_user, db)

    from ..services.volume_manager import get_volume_manager

    vm = get_volume_manager()
    graph = await vm.get_manifest_graph(project.volume_id)

    head = graph.get("head", "")
    raw_branches = graph.get("branches") or {}
    raw_snapshots = graph.get("snapshots") or []

    # Build a set of all snapshot hashes for quick lookup.
    snap_map: dict[str, dict] = {s["hash"]: s for s in raw_snapshots if isinstance(s, dict)}

    # Count checkpoints reachable from a given hash by walking prev pointers.
    def _count_checkpoints(tip_hash: str) -> int:
        count = 0
        h = tip_hash
        seen: set[str] = set()
        while h and h in snap_map and h not in seen:
            seen.add(h)
            if snap_map[h].get("role") == "checkpoint":
                count += 1
            h = snap_map[h].get("prev") or snap_map[h].get("parent", "")
        return count

    # Build branch list.
    branches: list[TimelineBranch] = []

    # Current branch (HEAD lineage) is always first.
    branches.append(
        TimelineBranch(
            name="main",
            display_name="Current",
            hash=head,
            is_current=True,
            checkpoint_count=_count_checkpoints(head),
        )
    )

    # Named branches from manifest.
    for name, tip_hash in raw_branches.items():
        # Convert "pre-restore-20260413-143000" to "Before restore (Apr 13, 2:30 PM)"
        display = _friendly_branch_name(name)
        branches.append(
            TimelineBranch(
                name=name,
                display_name=display,
                hash=tip_hash,
                is_current=False,
                checkpoint_count=_count_checkpoints(tip_hash),
            )
        )

    # Return ALL snapshots so the frontend can walk prev chains correctly.
    # The frontend renders checkpoints as full cards and counts syncs between them.
    timeline_snapshots = [
        TimelineSnapshot(
            hash=s.get("hash", ""),
            parent=s.get("parent", ""),
            prev=s.get("prev") or s.get("parent", ""),
            role=s.get("role", ""),
            label=s.get("label", ""),
            ts=s.get("ts", ""),
            consolidation=bool(s.get("consolidation", False)),
        )
        for s in raw_snapshots
        if isinstance(s, dict)
    ]

    return TimelineGraphResponse(
        head=head,
        branches=branches,
        snapshots=timeline_snapshots,
    )


def _friendly_branch_name(name: str) -> str:
    """Convert internal branch names to user-friendly display names.

    ``pre-restore-20260413-143000`` → ``Before restore (Apr 13, 2:30 PM)``
    """
    import re
    from datetime import datetime

    m = re.match(r"pre-restore-(\d{8})-(\d{6})", name)
    if m:
        try:
            dt = datetime.strptime(f"{m.group(1)}{m.group(2)}", "%Y%m%d%H%M%S")
            return f"Before restore ({dt.strftime('%b %-d, %-I:%M %p')})"
        except ValueError:
            pass
    return name


@router.post("/branches", response_model=CreateBranchResponse, status_code=status.HTTP_201_CREATED)
async def create_branch(
    project_id: UUID,
    request: CreateBranchRequest,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a named branch at the current HEAD position."""
    project = await _get_project(project_id, current_user, db)

    from ..services.volume_manager import get_volume_manager

    vm = get_volume_manager()
    graph = await vm.get_manifest_graph(project.volume_id)
    head = graph.get("head", "")
    if not head:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No snapshots to branch from"
        )

    # Sanitize name: lowercase, replace spaces with hyphens, strip non-alnum.
    import re

    slug = re.sub(r"[^a-z0-9-]", "", request.name.lower().replace(" ", "-")).strip("-")
    if not slug:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid branch name")

    try:
        await vm.create_branch(project.volume_id, slug, head)
    except Exception as e:
        logger.error("[SNAPSHOTS] Failed to create branch '%s': %s", slug, e)
        raise HTTPException(status_code=500, detail=f"Failed to create branch: {e}") from e

    return CreateBranchResponse(
        name=slug,
        display_name=request.name,
    )


@router.post("/", response_model=CASSnapshotCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_snapshot(
    project_id: UUID,
    request: CASSnapshotCreateRequest,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a CAS checkpoint snapshot (save current state)."""
    project = await _get_project(project_id, current_user, db)

    from ..services.volume_manager import get_volume_manager

    vm = get_volume_manager()
    try:
        hash_val = await vm.create_snapshot(project.volume_id, label=request.label or "Manual save")
    except Exception as e:
        logger.error("[SNAPSHOTS] Failed to create snapshot for %s: %s", project.volume_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to create snapshot: {e}") from e

    return CASSnapshotCreateResponse(
        hash=hash_val,
        label=request.label or "Manual save",
        volume_id=project.volume_id,
    )


@router.post("/{snapshot_hash}/restore", response_model=CASSnapshotRestoreResponse)
async def restore_snapshot(
    project_id: UUID,
    snapshot_hash: str,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Restore a project volume to a specific CAS snapshot.

    Calls RestoreToSnapshot directly for speed. Falls back to full
    recover_volume() if the direct call fails (e.g. node is down).
    """
    project = await _get_project(project_id, current_user, db)

    from ..services.volume_manager import get_volume_manager

    vm = get_volume_manager()
    node_name = project.cache_node or ""
    try:
        # Fast path: direct restore (skips ensure_cached + FileOps probe)
        await vm.restore_to_snapshot(project.volume_id, snapshot_hash)
    except Exception as direct_err:
        logger.warning(
            "[SNAPSHOTS] Direct restore failed for %s, falling back to recover: %s",
            project.volume_id,
            direct_err,
        )
        try:
            result = await vm.recover_volume(project.volume_id, target_hash=snapshot_hash)
            node_name = result["node_name"]
        except Exception as e:
            logger.error(
                "[SNAPSHOTS] Restore failed for %s → %s: %s",
                project.volume_id,
                snapshot_hash[:16],
                e,
            )
            raise HTTPException(status_code=503, detail=f"Restore failed: {e}") from e

    # Update cache_node
    if node_name:
        project.cache_node = node_name
        await db.commit()

    # Bounce compute pods so dev servers remount the restored volume.
    # The btrfs restore replaces the subvolume, which invalidates inotify
    # watches in running containers. Fire-and-forget: the file tree refresh
    # uses FileOps (podless) so it sees correct files immediately. The pod
    # bounce only affects live-reload/preview which recovers when the new
    # pod starts.
    try:
        from ..services.orchestration import is_kubernetes_mode

        if is_kubernetes_mode():
            namespace = f"proj-{project_id}"

            async def _bounce_pods() -> None:
                try:
                    from kubernetes import client as k8s_client
                    from kubernetes import config as k8s_config

                    k8s_config.load_incluster_config()
                    v1 = k8s_client.CoreV1Api()
                    pods = await asyncio.to_thread(
                        v1.list_namespaced_pod,
                        namespace=namespace,
                        label_selector="tesslate.io/component in (dev-container,service-container)",
                    )
                    for pod in pods.items:
                        await asyncio.to_thread(
                            v1.delete_namespaced_pod,
                            name=pod.metadata.name,
                            namespace=namespace,
                        )
                    logger.info(
                        "[SNAPSHOTS] Bounced %d compute pod(s) in %s", len(pods.items), namespace
                    )
                except Exception as bounce_err:
                    logger.warning(
                        "[SNAPSHOTS] Failed to bounce pods in %s: %s", namespace, bounce_err
                    )

            asyncio.create_task(_bounce_pods())
    except Exception:
        pass

    return CASSnapshotRestoreResponse(
        success=True,
        message=f"Restored to {snapshot_hash[:16]}",
        restored_hash=snapshot_hash,
        node=node_name,
    )
