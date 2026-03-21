# Snapshot Manager Service

The `SnapshotManager` service handles Kubernetes VolumeSnapshot operations for project persistence in Kubernetes mode. It replaced the previous S3-based hibernation system with a faster, more reliable approach using CSI-backed VolumeSnapshots.

## Overview

**File**: `orchestrator/app/services/snapshot_manager.py`

**Purpose**: Create, restore, and manage Kubernetes VolumeSnapshots for project data persistence and versioning.

> **Broader storage context**: The SnapshotManager handles *hibernation and user-facing timeline snapshots* using Kubernetes VolumeSnapshots. It operates alongside the Volume Hub/btrfs CSI architecture, which manages *project volume lifecycle* (creation from templates, cache placement, S3 sync). The SnapshotManager is CSI-agnostic — it works with any CSI driver that implements the VolumeSnapshot API (EBS CSI on AWS, btrfs CSI on self-hosted). The `k8s_snapshot_class` config setting determines which VolumeSnapshotClass is used.

## Key Features

| Feature | Description |
|---------|-------------|
| **Non-blocking** | Snapshot creation returns immediately; frontend polls for status |
| **Near-instant restore** | CSI driver lazy-loads data from snapshot for fast startup |
| **Per-PVC snapshots** | Supports project-storage and service PVCs independently |
| **Per-PVC rotation** | Snapshot rotation (`_rotate_snapshots`) is scoped to each PVC |
| **Timeline UI** | Up to 5 snapshots per project for version history |
| **Soft delete** | Snapshots retained 30 days after project deletion |

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    SnapshotManager                                │
│                (Per-PVC Snapshot Management)                      │
├──────────────────────────────────────────────────────────────────┤
│  Public Methods                                                  │
│  ─────────────────────────────────────────────────────────────── │
│  create_snapshot(pvc_name)         │  Creates VolumeSnapshot     │
│  restore_from_snapshot(pvc_name)   │  Creates PVC from snap      │
│  wait_for_snapshot_ready           │  Polls readyToUse: true     │
│  get_project_snapshots             │  Lists for Timeline UI      │
│  get_latest_ready_snapshot(pvc)    │  Latest per specific PVC    │
│  get_latest_ready_snapshots_by_pvc │  Dict of PVC→snapshot       │
│  has_existing_snapshot             │  Check restore eligibility  │
│  soft_delete_project_snapshots     │  30-day retention           │
│  cleanup_expired_snapshots         │  Deletes old soft-del       │
│                                                                  │
│  Private Methods                                                 │
│  ─────────────────────────────────────────────────────────────── │
│  _get_project_namespace            │  Resolves proj-{id} ns      │
│  _generate_snapshot_name           │  snap-/manual- + timestamp  │
│  _rotate_snapshots (per PVC)       │  Rotation scoped to PVC     │
│  _delete_snapshot                  │  Deletes VS + VSC + DB row  │
│  _ensure_volumesnapshot_exists     │  Recreates VS from retained │
│                                    │  VolumeSnapshotContent      │
│  _get_pvc_size_bytes               │  Reads PVC storage size     │
│  _parse_storage_size               │  Parses K8s size strings    │
└──────────────────────────────────────────────────────────────────┘
```

## Core Methods

### create_snapshot()

Creates a Kubernetes VolumeSnapshot from a project's PVC.

After creating the VolumeSnapshot, the operation order is: (1) rotate old snapshots via `_rotate_snapshots()` (scoped to the same PVC), (2) mark all existing snapshots for the same PVC as `is_latest=False`, (3) insert the new record with `is_latest=True`.

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

When the snapshot becomes ready, this method also updates `project.latest_snapshot_id` to point to the new snapshot.

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

    CSI driver lazy-loads data on first read - near-instant startup.

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
    db: AsyncSession,
    include_soft_deleted: bool = False
) -> list[ProjectSnapshot]:
    """
    Get all snapshots for project, ordered by created_at DESC.
    Maximum of 5 snapshots (older ones auto-rotated).
    Optionally includes soft-deleted snapshots.
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

### _ensure_volumesnapshot_exists() (private)

Handles cross-namespace snapshot restoration. When a project hibernates, its namespace and VolumeSnapshot are deleted, but the VolumeSnapshotContent is retained (due to `deletionPolicy: Retain`). On restore, this method recreates a pre-provisioned VolumeSnapshot from the retained content:

1. Checks if VolumeSnapshot already exists in the target namespace
2. If not, searches for the retained VolumeSnapshotContent by `volumeSnapshotRef`
3. Extracts the underlying `snapshotHandle` (e.g., EBS snapshot ID)
4. Creates a new pre-provisioned VolumeSnapshotContent pointing to the same underlying snapshot
5. Creates a VolumeSnapshot bound to the new content
6. Polls up to 10 times (1-second intervals) for `readyToUse: true`; if not ready after 10 iterations, proceeds optimistically (returns `True` and logs "created (may still be syncing)") since the snapshot should still work for PVC creation

### _delete_snapshot() (private)

Deletes a snapshot from both Kubernetes and the database. Because the VolumeSnapshotClass uses `deletionPolicy: Retain`, this method must explicitly clean up both the VolumeSnapshot and its bound VolumeSnapshotContent to avoid orphaned resources. The method:

1. Reads the VolumeSnapshot to find its `boundVolumeSnapshotContentName`
2. Deletes the VolumeSnapshot (namespaced)
3. Deletes the VolumeSnapshotContent (cluster-scoped)
4. Hard-deletes the database row via `db.delete(snapshot)`

> **Deletion path asymmetry**: `_delete_snapshot()` hard-deletes the DB row (`db.delete()`), permanently removing it from the database. In contrast, `cleanup_expired_snapshots()` sets `status='deleted'` but keeps the DB row — it is a logical delete that preserves an audit trail of cleaned-up snapshots. These two methods use different deletion semantics intentionally.

## API Endpoints

The `routers/snapshots.py` router exposes four endpoints under `/api/projects/{project_id}/snapshots`:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | `GET` | List all snapshots for project (Timeline UI) |
| `/` | `POST` | Create a manual snapshot (non-blocking, returns `pending`) |
| `/{snapshot_id}` | `GET` | Get details of a specific snapshot (used for polling status) |
| `/{snapshot_id}/restore` | `POST` | Set project to restore from a specific snapshot on next start |

The restore endpoint does **not** perform the restore immediately. It sets `project.latest_snapshot_id` to the chosen snapshot. The actual PVC creation from snapshot happens when the project is started via `KubernetesOrchestrator._restore_from_snapshot()`.

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

    return success  # PVCs ready immediately (CSI lazy-loads)
```

## Configuration

Settings in `config.py`:

```python
k8s_snapshot_class: str = "tesslate-ebs-snapshots"            # VolumeSnapshotClass name
k8s_snapshot_retention_days: int = 30                          # Soft-delete retention
k8s_max_snapshots_per_project: int = 5                         # Timeline limit (per PVC)
k8s_snapshot_ready_timeout_seconds: int = 300                  # Wait timeout (EBS/CSI under load)
k8s_pvc_size: str = "5Gi"                                     # PVC size on restore
k8s_pvc_access_mode: str = "ReadWriteOnce"                     # PVC access mode on restore
k8s_storage_class: str = "tesslate-block-storage"              # StorageClass for restored PVCs
k8s_namespace_per_project: bool = True                         # Namespace isolation mode
```

## Database Model

```python
class ProjectSnapshot(Base):
    __tablename__ = "project_snapshots"

    id = Column(UUID, primary_key=True)
    project_id = Column(UUID, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # K8s references
    snapshot_name = Column(String(255), index=True)  # VolumeSnapshot name
    snapshot_namespace = Column(String(255))
    pvc_name = Column(String(255))

    # Metadata
    snapshot_type = Column(String(50))  # "hibernation" or "manual"
    status = Column(String(50))         # "pending", "ready", "error", "deleted"
    label = Column(String(255))         # User-provided label
    volume_size_bytes = Column(BigInteger)
    is_latest = Column(Boolean, default=False)

    # Soft delete
    is_soft_deleted = Column(Boolean, default=False)
    soft_delete_expires_at = Column(DateTime(timezone=True))

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    ready_at = Column(DateTime(timezone=True))

    # Composite indexes
    __table_args__ = (
        Index("ix_project_snapshots_project_created", "project_id", "created_at"),
        Index("ix_project_snapshots_soft_delete", "is_soft_deleted", "soft_delete_expires_at"),
    )
```

## Kubernetes Resources

The SnapshotManager is CSI-agnostic — it uses the standard `snapshot.storage.k8s.io/v1` API.
The `k8s_snapshot_class` config setting determines the VolumeSnapshotClass:

| Environment | `k8s_snapshot_class` | CSI Driver |
|-------------|---------------------|------------|
| AWS EKS | `tesslate-ebs-snapshots` | `ebs.csi.aws.com` |
| Minikube | `tesslate-btrfs-snapshots` | btrfs CSI driver |

### VolumeSnapshotClass (example — AWS)

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: tesslate-ebs-snapshots
driver: ebs.csi.aws.com
deletionPolicy: Retain  # Keep underlying snapshot when VolumeSnapshot deleted
```

### VolumeSnapshot (Created by SnapshotManager)

Snapshot names use the format `{prefix}-{project_id[:8]}-{timestamp}` where prefix is `snap` for hibernation or `manual` for manual snapshots.

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: snap-{project_id[:8]}-{YYYYMMDD-HHMMSS}
  namespace: proj-{project_id}
  labels:
    app: tesslate
    managed-by: tesslate-backend
    project-id: "{project_id}"
    user-id: "{user_id}"
    snapshot-type: hibernation
spec:
  volumeSnapshotClassName: tesslate-ebs-snapshots  # from k8s_snapshot_class config
  source:
    persistentVolumeClaimName: project-storage
```

### PVC from Snapshot (Created on Restore)

PVC size and access mode are read from `k8s_pvc_size` and `k8s_pvc_access_mode` config settings.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: project-storage
  namespace: proj-{project_id}
spec:
  storageClassName: tesslate-block-storage  # from k8s_storage_class config
  dataSource:
    name: snap-{project_id[:8]}-{timestamp}
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
  accessModes: [ReadWriteOnce]  # from k8s_pvc_access_mode config
  resources:
    requests:
      storage: 5Gi  # from k8s_pvc_size config
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

## Performance

| Metric | Previous (S3 ZIP, removed) | Current (VolumeSnapshot) |
|--------|---------------------------|--------------------------|
| Hibernation time | 30-60 seconds | < 5 seconds to initiate |
| Restore time | 30-90 seconds | < 10 seconds (lazy loading) |
| npm install on restore | Always (30-60s) | Never (volume preserved) |
| User-visible wait | "Restoring..." | "Starting..." |

Note: Actual snapshot readiness time depends on CSI driver and volume size. The `wait_for_snapshot_ready` timeout defaults to 300 seconds to handle CSI drivers under load.

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
- `orchestrator/app/services/orchestration/kubernetes_orchestrator.py` - Calls SnapshotManager for hibernation/restore
- `orchestrator/app/routers/projects.py` - Calls `soft_delete_project_snapshots` on project deletion
- `orchestrator/app/models.py` - ProjectSnapshot model
- `orchestrator/app/services/volume_manager.py` - Volume Hub client (parallel storage system for volume lifecycle)
- `k8s/base/core/cleanup-cronjob.yaml` - Hibernation cleanup (idle project detection)
- `k8s/base/core/snapshot-cleanup-cronjob.yaml` - Soft-delete cleanup (expired snapshot deletion)
- `k8s/terraform/aws/eks.tf` - VolumeSnapshotClass definition (AWS)
