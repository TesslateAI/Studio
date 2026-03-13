# Snapshot Manager Service

The `SnapshotManager` service handles EBS VolumeSnapshot operations for project persistence in Kubernetes mode. It replaces the previous S3-based hibernation system with a faster, more reliable approach.

## Overview

**File**: `orchestrator/app/services/snapshot_manager.py`

**Purpose**: Create, restore, and manage EBS VolumeSnapshots for project data persistence and versioning.

## Key Features

| Feature | Description |
|---------|-------------|
| **Non-blocking** | Snapshot creation returns immediately; frontend polls for status |
| **Near-instant restore** | EBS lazy-loads data from snapshot for fast startup |
| **Per-PVC snapshots** | Supports project-storage and service PVCs independently |
| **Per-PVC rotation** | Snapshot rotation (`_rotate_snapshots`) is scoped to each PVC |
| **Timeline UI** | Up to 5 snapshots per project for version history |
| **Soft delete** | Snapshots retained 30 days after project deletion |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    SnapshotManager                           │
│                (Per-PVC Snapshot Management)                 │
├─────────────────────────────────────────────────────────────┤
│  create_snapshot(pvc_name)         │  Creates VolumeSnapshot │
│  restore_from_snapshot(pvc_name)   │  Creates PVC from snap  │
│  wait_for_snapshot_ready           │  Polls readyToUse: true │
│  get_project_snapshots             │  Lists for Timeline UI  │
│  get_latest_ready_snapshot(pvc)    │  Latest per specific PVC│
│  get_latest_ready_snapshots_by_pvc │  Dict of PVC→snapshot   │
│  soft_delete_project_snapshots     │  30-day retention       │
│  cleanup_expired_snapshots         │  Deletes old soft-del   │
│  _rotate_snapshots (per PVC)       │  Rotation scoped to PVC │
└─────────────────────────────────────────────────────────────┘
```

## Core Methods

### create_snapshot()

Creates an EBS VolumeSnapshot from a project's PVC.

Before inserting the new record, marks all existing snapshots for the same PVC as `is_latest=False`, then sets `is_latest=True` on the new record. Snapshot rotation (`_rotate_snapshots`) is also scoped to the same PVC.

```python
async def create_snapshot(
    project_id: UUID,
    user_id: UUID,
    db: AsyncSession,
    snapshot_type: str = "hibernation",  # or "manual"
    label: Optional[str] = None,
    pvc_name: str = "project-storage"
) -> Tuple[Optional[ProjectSnapshot], Optional[str]]:
    """
    Create VolumeSnapshot (< 1 second to initiate).

    Returns immediately with 'pending' status.
    Caller should poll wait_for_snapshot_ready() if needed.

    Returns:
        (ProjectSnapshot record, None) on success
        (None, error_message) on failure
    """
```

### wait_for_snapshot_ready()

Waits for a snapshot to become ready (for hibernation workflow only).

```python
async def wait_for_snapshot_ready(
    snapshot: ProjectSnapshot,
    db: AsyncSession,
    timeout_seconds: int | None = None  # Default from config (300s)
) -> Tuple[bool, Optional[str]]:
    """
    Poll until VolumeSnapshot status.readyToUse is true.

    CRITICAL: Must wait for ready before deleting PVC!

    Returns:
        (True, None) when ready
        (False, error_message) on timeout or error
    """
```

Progress logging uses `logger.info` (not `logger.debug`) and includes `readyToUse`, `error`, and `boundVolumeSnapshotContentName` fields every 5 seconds.

On timeout, the error message includes enhanced diagnostics: the last observed `readyToUse` value, any `error` from the VolumeSnapshot status, and the `boundVolumeSnapshotContentName` if present.

### restore_from_snapshot()

Creates a PVC from a VolumeSnapshot for project restoration. Internally delegates to `get_latest_ready_snapshot()` when no specific `snapshot_id` is provided.

```python
async def restore_from_snapshot(
    project_id: UUID,
    user_id: UUID,
    db: AsyncSession,
    snapshot_id: Optional[UUID] = None,  # Uses latest if None
    pvc_name: str = "project-storage"
) -> Tuple[bool, Optional[str]]:
    """
    Create PVC with dataSource pointing to VolumeSnapshot.

    EBS lazy-loads data on first read - near-instant startup.

    Returns:
        (True, None) on success
        (False, error_message) on failure (includes PVC name in message)
    """
```

### get_latest_ready_snapshot()

Returns the single latest ready snapshot for a specific PVC in a project.

```python
async def get_latest_ready_snapshot(
    project_id: UUID,
    db: AsyncSession,
    pvc_name: str,
    snapshot_type: Optional[str] = None
) -> Optional[ProjectSnapshot]:
    """
    Get the latest ready snapshot for a specific PVC.
    Filters by status="ready" and is_soft_deleted=False.
    Optional snapshot_type filter ("hibernation" or "manual").
    """
```

### get_latest_ready_snapshots_by_pvc()

Returns a dict mapping PVC names to their latest ready snapshot for a project.

```python
async def get_latest_ready_snapshots_by_pvc(
    project_id: UUID,
    db: AsyncSession,
    snapshot_type: Optional[str] = None
) -> dict[str, ProjectSnapshot]:
    """
    Get the latest ready snapshot for each PVC in a project.
    Returns {pvc_name: ProjectSnapshot} mapping.
    Optional snapshot_type filter.
    """
```

### get_project_snapshots()

Lists snapshots for a project (Timeline UI).

```python
async def get_project_snapshots(
    project_id: UUID,
    db: AsyncSession
) -> List[ProjectSnapshot]:
    """
    Get all snapshots for project, ordered by created_at DESC.
    Maximum of 5 snapshots (older ones auto-rotated).
    """
```

### soft_delete_project_snapshots()

Marks snapshots for retention when project is deleted.

```python
async def soft_delete_project_snapshots(
    project_id: UUID,
    db: AsyncSession
) -> int:
    """
    Mark all project snapshots as soft-deleted.
    Sets soft_delete_expires_at to 30 days from now.
    K8s VolumeSnapshots NOT deleted immediately.

    Returns: Number of snapshots marked
    """
```

### cleanup_expired_snapshots()

Deletes expired soft-deleted snapshots (daily cronjob).

```python
async def cleanup_expired_snapshots(
    db: AsyncSession
) -> int:
    """
    Delete K8s VolumeSnapshots where soft_delete_expires_at < now.

    Called by snapshot-cleanup-cronjob.yaml daily at 3 AM UTC.

    Returns: Number of snapshots deleted
    """
```

### has_existing_snapshot()

Checks if a project has any ready snapshots (for restore eligibility).

```python
async def has_existing_snapshot(
    project_id: UUID,
    db: AsyncSession,
    pvc_name: Optional[str] = None,
    snapshot_type: Optional[str] = None
) -> bool:
    """
    Check if a project has any ready, non-soft-deleted snapshots.
    Optional pvc_name and snapshot_type filters to narrow the check.
    """
```

## Usage Patterns

### Manual Snapshot (API Endpoint)

```python
# In routers/snapshots.py
@router.post("/projects/{project_id}/snapshots/")
async def create_manual_snapshot(project_id: UUID, request: SnapshotCreate, ...):
    snapshot_manager = get_snapshot_manager()

    # Create snapshot - returns immediately with 'pending' status
    snapshot, error = await snapshot_manager.create_snapshot(
        project_id=project_id,
        user_id=current_user.id,
        db=db,
        snapshot_type="manual",
        label=request.label or "Manual save"
    )

    # Return immediately - frontend polls for 'ready' status
    return SnapshotResponse(id=snapshot.id, status="pending", ...)
```

### Hibernation Snapshot (Background Task — Multi-PVC)

```python
# In kubernetes_orchestrator.py
async def _save_to_snapshot(self, project_id, user_id, namespace, db):
    snapshot_manager = get_snapshot_manager()

    # Discover all PVCs: project-storage + service PVCs
    pvc_names = await self._get_hibernation_pvc_names(namespace)
    # e.g. ["project-storage", "svc-postgres-data"]

    # Create snapshot for each PVC
    for pvc_name in pvc_names:
        snapshot, error = await snapshot_manager.create_snapshot(
            project_id, user_id, db,
            snapshot_type="hibernation",
            pvc_name=pvc_name  # Per-PVC snapshot
        )

        # CRITICAL: Wait for ready before deleting namespace!
        success, wait_error = await snapshot_manager.wait_for_snapshot_ready(snapshot, db)
        if not success:
            return False  # Abort — don't delete namespace

    return True
```

### Project Restoration (Multi-PVC)

```python
# In kubernetes_orchestrator.py
async def _restore_from_snapshot(self, project_id, user_id, namespace, db):
    snapshot_manager = get_snapshot_manager()

    # 1. Restore project-storage PVC first
    success, error = await snapshot_manager.restore_from_snapshot(
        project_id, user_id, db, pvc_name="project-storage"
    )

    # 2. Restore service PVCs
    service_snapshots = await snapshot_manager.get_latest_ready_snapshots_by_pvc(
        project_id, db, snapshot_type="hibernation"
    )
    for pvc_name, snapshot in service_snapshots.items():
        if pvc_name != "project-storage":
            await snapshot_manager.restore_from_snapshot(
                project_id, user_id, db,
                snapshot_id=snapshot.id, pvc_name=pvc_name
            )

    return success  # PVCs ready immediately (EBS lazy-loads)
```

## Configuration

Settings in `config.py`:

```python
k8s_snapshot_class: str = "tesslate-ebs-snapshots"  # VolumeSnapshotClass name
k8s_snapshot_retention_days: int = 30               # Soft-delete retention
k8s_max_snapshots_per_project: int = 5              # Timeline limit
k8s_snapshot_ready_timeout_seconds: int = 300       # Wait timeout (increased for EBS/CSI under load)
```

## Database Model

```python
class ProjectSnapshot(Base):
    __tablename__ = "project_snapshots"

    id = Column(UUID, primary_key=True)
    project_id = Column(UUID, ForeignKey("projects.id", ondelete="SET NULL"))
    user_id = Column(UUID, ForeignKey("users.id", ondelete="SET NULL"))

    # K8s references
    snapshot_name = Column(String(255), index=True)  # VolumeSnapshot name
    snapshot_namespace = Column(String(255))
    pvc_name = Column(String(255))

    # Metadata
    snapshot_type = Column(String(50))  # "hibernation" or "manual"
    status = Column(String(50))         # "pending", "ready", "error", "deleted"
    label = Column(String(255))         # User-provided label
    volume_size_bytes = Column(BigInteger)
    is_latest = Column(Boolean, default=True)

    # Soft delete
    is_soft_deleted = Column(Boolean, default=False)
    soft_delete_expires_at = Column(DateTime)

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    ready_at = Column(DateTime)
```

## Kubernetes Resources

### VolumeSnapshotClass

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: tesslate-ebs-snapshots
driver: ebs.csi.aws.com
deletionPolicy: Retain  # Keep EBS snapshot when VolumeSnapshot deleted
```

### VolumeSnapshot (Created by SnapshotManager)

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: snap-{project_id}-{timestamp}
  namespace: proj-{project_id}
spec:
  volumeSnapshotClassName: tesslate-ebs-snapshots
  source:
    persistentVolumeClaimName: project-storage
```

### PVC from Snapshot (Created on Restore)

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: project-storage
  namespace: proj-{project_id}
spec:
  storageClassName: tesslate-block-storage
  dataSource:
    name: snap-{project_id}-{timestamp}
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 10Gi
```

## Cleanup CronJobs

### Hibernation Cleanup (`cleanup-cronjob.yaml`)

- **Schedule**: Every 2 minutes
- **Purpose**: Create snapshots for idle projects, then delete namespace
- **Logic**:
  1. Find projects with `last_activity` older than idle threshold
  2. Call `create_snapshot()` and `wait_for_snapshot_ready()`
  3. Delete namespace only after snapshot is ready

### Snapshot Cleanup (`snapshot-cleanup-cronjob.yaml`)

- **Schedule**: Daily at 3 AM UTC
- **Purpose**: Delete expired soft-deleted snapshots
- **Logic**:
  1. Query `project_snapshots` where `soft_delete_expires_at < now`
  2. Delete K8s VolumeSnapshot for each
  3. Update database record status to "deleted"

## Performance Comparison

| Metric | Old (S3 ZIP) | New (EBS Snapshot) |
|--------|--------------|-------------------|
| Hibernation time | 30-60 seconds | < 5 seconds |
| Restore time | 30-90 seconds | < 10 seconds |
| npm install on restore | Always (30-60s) | Never (preserved) |
| User-visible wait | "Restoring..." | "Starting..." |

## Troubleshooting

### Snapshot stuck in "pending"

```bash
# Check VolumeSnapshot status
kubectl get volumesnapshot -n proj-<uuid>
kubectl describe volumesnapshot <name> -n proj-<uuid>

# Check snapshot controller logs
kubectl logs -n kube-system -l app=snapshot-controller
```

### Restore failing

```bash
# Check if snapshot exists and is ready
kubectl get volumesnapshot -n proj-<uuid> -o yaml | grep readyToUse

# Check PVC events
kubectl describe pvc project-storage -n proj-<uuid>
```

### Cleanup not working

```bash
# Check cronjob status
kubectl get cronjob -n tesslate
kubectl get jobs -n tesslate

# Check cleanup pod logs
kubectl logs -n tesslate -l job-name=snapshot-cleanup-<timestamp>
```

## Related Files

- `orchestrator/app/routers/snapshots.py` - API endpoints for Timeline UI
- `orchestrator/app/services/orchestration/kubernetes_orchestrator.py` - Integration
- `orchestrator/app/models.py` - ProjectSnapshot model
- `k8s/base/core/cleanup-cronjob.yaml` - Hibernation cleanup
- `k8s/base/core/snapshot-cleanup-cronjob.yaml` - Soft-delete cleanup
- `k8s/terraform/aws/eks.tf` - VolumeSnapshotClass definition
