# Storage Architecture

This document describes Tesslate Studio's three-layer storage architecture: the Volume Hub (storageless orchestrator), btrfs CSI node drivers (node-native storage), and the CAS Layer Store (content-addressed object storage). It also covers the Python integration layer, the legacy SnapshotManager, storage class configuration, and the full volume lifecycle.

## Overview

Tesslate Studio uses a purpose-built storage stack designed for instant project creation via copy-on-write cloning, cross-node volume migration, and durable persistence to object storage. The system is split into three tiers:

| Layer | Role | Runs As | Storage |
|-------|------|---------|---------|
| **Volume Hub** | Storageless orchestrator; coordinates nodes, tracks ownership, routes operations | K8s Deployment (no PVC, no SYS_ADMIN) | None (in-memory registry, rebuilt from nodes on restart) |
| **btrfs CSI Node** | Node-native btrfs operations: subvolume CRUD, CoW cloning, send/receive, sync daemon | K8s DaemonSet (privileged, btrfs pool at `/mnt/tesslate-pool`) | Local btrfs filesystem |
| **CAS Layer Store** | Content-addressed blob storage in S3-compatible object storage | Embedded in each CSI node process | S3 / GCS / Azure Blob (via rclone) |

The Python orchestrator backend communicates exclusively with the Hub via gRPC. It never talks to individual nodes or touches object storage directly. The Hub delegates all data operations to nodes via the internal NodeOps gRPC service.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          Python Orchestrator (FastAPI)                          │
│                                                                                 │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────┐                      │
│  │ VolumeManager│   │  HubClient   │   │SnapshotManager │                      │
│  │  (singleton) │──▶│ gRPC :9750   │   │(K8s VolumeSnap)│                      │
│  └──────────────┘   └──────┬───────┘   └────────────────┘                      │
│                            │                                                    │
└────────────────────────────┼────────────────────────────────────────────────────┘
                             │ gRPC (JSON codec)
                             ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     Volume Hub  (Deployment, port 9750)                         │
│                                                                                 │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐                    │
│  │ NodeRegistry │   │ NodeResolver │   │ CAS Store        │                    │
│  │ vol→owner    │   │ K8s Endpoints│   │ (manifest reads) │                    │
│  │ vol→cached[] │   │ watch (~1s)  │   └──────────────────┘                    │
│  │ tmpl→nodes   │   │ node→podIP   │                                           │
│  └──────────────┘   └──────────────┘                                           │
│         │                    │                                                  │
│         │   NodeOps gRPC     │  resolves node name → pod IP                    │
│         └────────────────────┼──────────────────┐                              │
│                              │                  │                              │
└──────────────────────────────┼──────────────────┼──────────────────────────────┘
                               │                  │
                    ┌──────────▼──────┐  ┌────────▼────────┐
                    │  CSI Node A     │  │  CSI Node B      │
                    │  (DaemonSet)    │  │  (DaemonSet)     │
                    │                 │  │                  │
                    │ :9741 NodeOps   │  │ :9741 NodeOps    │
                    │  (gRPC)         │  │  (gRPC)          │
                    │ :9742 FileOps   │  │ :9742 FileOps    │
                    │  (gRPC)         │  │  (gRPC)          │
                    │ :9743 Drain     │  │ :9743 Drain      │
                    │  (HTTP: POST    │  │  (HTTP: POST     │
                    │   /drain, GET   │  │   /drain, GET    │
                    │   /healthz)     │  │   /healthz)      │
                    │                 │  │                  │
                    │ btrfs pool:     │  │ btrfs pool:      │
                    │  /volumes/      │  │  /volumes/       │
                    │  /templates/    │  │  /templates/     │
                    │  /snapshots/    │  │  /snapshots/     │
                    │  /layers/       │  │  /layers/        │
                    │                 │  │                  │
                    │ Sync Daemon ──────────────────┐      │
                    │ GC Collector    │  │            │      │
                    └─────────────────┘  └────────────┼──────┘
                                                     │
                                                     ▼
                                        ┌─────────────────────┐
                                        │   Object Storage     │
                                        │   (S3 / GCS / Azure) │
                                        │                      │
                                        │ blobs/sha256:*.zst   │
                                        │ manifests/*.json     │
                                        │ index/templates.json │
                                        └─────────────────────┘
```

## Volume Hub

The Hub is a **storageless orchestrator**. It holds zero storage and zero btrfs state. Its sole purpose is coordinating nodes for volume lifecycle, cache placement, and S3 sync triggers.

### Deployment Model

- Runs as a K8s **Deployment** (not StatefulSet) -- no PVC, no `SYS_ADMIN` capability.
- Listens on TCP port **9750** for VolumeHub gRPC.
- Also serves the CSI Controller gRPC on a unix socket for `csi-provisioner` and `csi-snapshotter` sidecars.
- Registry is rebuilt from node queries on restart; no persistent state required.

### In-Memory Registry (NodeRegistry)

The Hub maintains an in-memory `NodeRegistry` that tracks:

| Mapping | Purpose |
|---------|---------|
| `volumeID -> ownerNode` | Authoritative owner for sync and mutation |
| `volumeID -> cachedNodes[]` | Nodes that have a local copy (for fast path and peer transfer) |
| `volumeID -> templateName, templateHash, latestHash` | CAS metadata for cache validation |
| `nodeName -> volumeIDs[]` | Inverse index for capacity-aware placement |
| `templateName -> nodeNames[]` | Template distribution tracking |

The registry provides `LeastLoadedNode()` for capacity-aware placement and `ReconcileNodes(liveNodes)` for stale entry cleanup.

### Node Discovery (NodeResolver)

The Hub discovers CSI node pods via the K8s **Endpoints watch API**:

- Watches the `tesslate-btrfs-csi-node-svc` headless service in `kube-system`.
- Maintains a `nodeToAddr` map: K8s node name to pod IP:port.
- Uses a streaming HTTP watch connection for approximately 1-second latency on node changes (compared to the previous 30-second polling approach).
- On watch disconnect or 410 Gone, falls back to list-then-rewatch with exponential backoff (1s to 30s cap).
- Each node change triggers `DiscoverNodes()` and `RebuildRegistry()` to reconcile Hub state.

### Liveness Filtering

The `EnsureCached` RPC is the core of the Hub's scheduling logic. It guarantees that the returned node is **both live and a valid candidate**:

1. Get the live node set from the K8s Endpoints watch.
2. Intersect caller-provided `candidate_nodes` with the live set. If all candidates are dead, return `FailedPrecondition`.
3. Get cached nodes from the registry and filter to live-only. Proactively remove stale entries for terminated nodes.
4. **Fast path**: If any live cached node is in the candidate set, return it immediately (zero data movement).
5. **Peer transfer**: If cached on a live non-candidate node, `SendVolumeTo` streams the volume to the best candidate via btrfs send/receive.
6. **CAS restore**: If no live cache exists (or peer transfer fails), restore from object storage on the best candidate.

The best candidate is chosen by `pickBestCandidate()`: the node with the fewest cached volumes, with deterministic tie-break by lexicographic order.

### gRPC Service

The Hub exposes the `volumehub.VolumeHub` gRPC service with JSON codec (`content-type: application/grpc+json`):

| RPC | Purpose |
|-----|---------|
| `CreateVolume(template?, hint_node?)` | Create volume on a node, optionally from a template clone. Returns `(volume_id, node_name)`. |
| `DeleteVolume(volume_id)` | Delete from Hub registry, S3 manifest, and all node caches. Idempotent. |
| `EnsureCached(volume_id, candidate_nodes?)` | Ensure volume is cached on a live schedulable node. See liveness filtering above. |
| `TriggerSync(volume_id)` | Look up owner node and trigger CAS sync. Non-blocking from caller. |
| `VolumeStatus(volume_id)` | Return ownership, cached nodes, sync time, layer count, and snapshots. |
| `CreateServiceVolume(base_volume_id, service_name)` | Create ephemeral service subvolume (e.g., postgres data dir). Not synced to S3. |
| `CreateSnapshot(volume_id, label?)` | Create a labeled CAS snapshot layer. |
| `ListSnapshots(volume_id)` | List snapshot layers from the CAS manifest. |
| `RestoreToSnapshot(volume_id, target_hash)` | Restore volume to a specific snapshot hash (truncates manifest). |

## btrfs CSI Driver

The CSI node driver runs as a **DaemonSet** on every compute node. It owns all volume data on local btrfs pools and provides node-native storage operations.

### Driver Modes

| Mode | K8s Workload | Services Registered | Use Case |
|------|-------------|---------------------|----------|
| `node` | DaemonSet | CSI Identity + Node, NodeOps, FileOps | Production multi-node |
| `hub` | Deployment | CSI Identity + Controller, VolumeHub gRPC | Production Hub pod |
| `all` | Single pod | CSI Identity + Controller + Node, NodeOps, FileOps, VolumeHub | Minikube / single-node testing |

### btrfs Pool Layout

Each node maintains a btrfs filesystem mounted at `/mnt/tesslate-pool` (initialized by the `init-btrfs-pool` init container, which creates a loopback image if needed):

```
/mnt/tesslate-pool/
├── volumes/          # Active project subvolumes (vol-{id})
├── templates/        # Read-only template subvolumes (e.g., templates/nextjs)
├── snapshots/        # Local snapshots for CAS sync (btrfs send source)
└── layers/           # CAS layer snapshots for incremental sync
```

Key btrfs operations:

| Operation | Speed | Used For |
|-----------|-------|----------|
| `btrfs subvolume snapshot` (CoW clone) | Instant (< 1ms) | Creating volumes from templates |
| `btrfs send` | Proportional to data size | Uploading to CAS, peer transfer |
| `btrfs receive` | Proportional to data size | Restoring from CAS, receiving peer transfer |
| `btrfs subvolume delete` | Instant | Volume cleanup |
| `btrfs qgroup limit` | Instant | Per-volume storage quotas |

### NodeOps gRPC Service (port 9741)

The internal gRPC service that the Hub (or CSI Controller) uses to delegate operations to nodes:

| Operation | Description |
|-----------|-------------|
| `CreateSubvolume` / `DeleteSubvolume` | btrfs subvolume lifecycle |
| `SnapshotSubvolume` | CoW snapshot (read-only or writable) |
| `SubvolumeExists` | Check if subvolume exists |
| `GetCapacity` | Total and available bytes on the pool |
| `ListSubvolumes` | List subvolumes matching a prefix |
| `TrackVolume` / `UntrackVolume` | Register/remove volume for periodic CAS sync |
| `EnsureTemplate` | Download template from CAS if not present locally |
| `RestoreVolume` | Replay CAS manifest layer chain to restore a volume |
| `PromoteToTemplate` | Snapshot a volume as read-only template, upload to CAS |
| `SyncVolume` | Trigger immediate CAS sync for a single volume |
| `DeleteVolumeCAS` | Delete CAS manifest and local layer snapshots |
| `SetOwnership` | Recursively chown a subvolume to a given uid:gid |
| `SendVolumeTo` / `SendTemplateTo` | Stream volume/template to target node via btrfs send/receive |
| `GetSyncState` | Return sync tracking state of all volumes on this node |
| `HasBlobs` | Check which blob hashes exist as local snapshots/templates |
| `CreateUserSnapshot` / `RestoreFromSnapshot` | Create/restore labeled snapshot layers |
| `GetVolumeMetadata` | Return CAS manifest metadata (layers, snapshots, hashes) |
| `SetQgroupLimit` / `GetQgroupUsage` | Per-volume storage quota management |

### FileOps gRPC Service (port 9742)

Direct filesystem operations on volumes, served only by nodes (not the Hub). The Python orchestrator connects to nodes via `FileOpsClient` to read/write project files with sub-millisecond latency:

- `ReadFile` / `WriteFile` / `DeletePath` -- single file operations
- `ReadFiles` -- batch multi-file read
- `ListDir` / `ListTree` -- directory listing (flat and recursive)
- `MkdirAll` -- recursive directory creation

### Template Manager

Templates are read-only btrfs subvolumes stored under `/mnt/tesslate-pool/templates/`. They serve as the base for instant CoW cloning when creating new projects.

Key behaviors:
- `EnsureTemplate(name)`: If present locally, ensure it is read-only (set in place, no delete+redownload). If missing, download from CAS.
- `EnsureTemplateByHash(name, hash)`: Hash-verified template download. If present locally, ensure read-only in place. If missing, download from CAS by the specified hash.
- `UploadTemplate(name)`: Sends the template directly to CAS via `btrfs send` and records the name-to-hash mapping in the template index.
- `RefreshTemplate(name)`: Force re-download from CAS (deletes existing, downloads fresh).
- Templates are sent directly (not via intermediate snapshot) so the btrfs UUID matches what is used as the `-p` parent in incremental layer sends. This enables cross-node incremental restore.

### Sync Daemon

Each node runs a background sync daemon that periodically uploads dirty volumes to CAS:

- Configurable interval (default: 60 seconds, set via `--sync-interval`).
- Tracks volumes registered via `TrackVolume()`.
- Creates incremental btrfs send streams (delta from last snapshot) and uploads as CAS blobs.
- Updates the volume manifest in object storage after each sync.
- `DrainAll()`: Called during graceful shutdown (preStop hook) to sync all tracked volumes before pod termination. The preStop hook polls for a sentinel file at `/run/csi/drain-complete`.

### Garbage Collector

Each node runs a GC collector that periodically cleans up orphaned resources:

- Runs every 10 minutes with a 24-hour grace period.
- Queries the orchestrator (`/api/internal/known-volume-ids`) to determine which volumes are still referenced by projects.
- Deletes orphaned subvolumes, stale snapshots, and unreferenced CAS blobs.
- Supports dry-run mode for safe testing.

### Graceful Shutdown

The CSI node uses a multi-step graceful shutdown process:

1. K8s sends SIGTERM, triggering the preStop hook.
2. preStop hook sends `POST /drain` to the local drain HTTP server (port 9743).
3. Drain handler calls `syncer.DrainAll()` to sync all tracked volumes to CAS.
4. On success, writes sentinel file `/run/csi/drain-complete`.
5. preStop hook polls for the sentinel file (up to 580 seconds).
6. `terminationGracePeriodSeconds` is set to 600 seconds to allow drain to complete.

## CAS Layer Store

The CAS (Content-Addressable Storage) layer store provides durable, deduplicated storage for volume data in S3-compatible object storage.

### Object Storage Abstraction

The `ObjectStorage` interface abstracts over cloud providers:

```go
type ObjectStorage interface {
    Upload(ctx, key, reader, size) error
    Download(ctx, key) (ReadCloser, error)
    Delete(ctx, key) error
    Exists(ctx, key) (bool, error)
    List(ctx, prefix) ([]ObjectInfo, error)
    Copy(ctx, srcKey, dstKey) error     // Server-side copy (zero bandwidth)
    EnsureBucket(ctx) error
}
```

The concrete implementation (`RcloneStorage`) shells out to the `rclone` binary using backend-specific remote path syntax (`:provider:bucket/key`). Provider configuration is passed via `RCLONE_*` environment variables. Supported providers: `s3`, `gcs`, `azureblob`.

### S3 Layout

```
bucket/
├── blobs/
│   ├── sha256:{hash1}.zst     # zstd-compressed btrfs send streams
│   ├── sha256:{hash2}.zst
│   └── _staging/              # Temporary upload keys (cleaned up after copy)
│       └── {random}.zst
├── manifests/
│   ├── vol-{id1}.json         # Layer chain per volume
│   └── vol-{id2}.json
└── index/
    └── templates.json         # Template name → blob hash mapping
```

### Blob Storage

Blobs are btrfs send streams compressed with zstd and addressed by their SHA256 hash:

1. **Upload pipeline**: `reader -> tee(SHA256 hasher) -> zstd compress -> pipe -> upload to staging key`.
2. **Dedup check**: Once hash is known, check if `blobs/sha256:{hash}.zst` exists. If yes, delete staging key and return (zero cost).
3. **Finalize**: Server-side copy from staging key to content-addressed key, then delete staging key.
4. **Download**: Download the compressed blob and decompress via zstd decoder. Caller receives a decompressed `ReadCloser`.

This design uses constant memory regardless of blob size and provides automatic deduplication across volumes and templates.

### Volume Manifests

Each volume has a manifest (`manifests/{volume_id}.json`) describing its layer chain:

```json
{
  "volume_id": "vol-a1b2c3d4",
  "base": "sha256:abc123...",
  "template_name": "nextjs",
  "layers": [
    {
      "hash": "sha256:def456...",
      "parent": "sha256:abc123...",
      "type": "sync",
      "ts": "2026-03-21T10:00:00Z"
    },
    {
      "hash": "sha256:ghi789...",
      "parent": "sha256:def456...",
      "type": "snapshot",
      "label": "Before refactor",
      "ts": "2026-03-21T12:00:00Z"
    }
  ]
}
```

- `base`: The template blob hash (the starting point).
- `layers`: Ordered chain of incremental btrfs send streams. Each layer's `parent` is the hash it was generated against.
- `type`: Either `"sync"` (periodic daemon sync) or `"snapshot"` (user-initiated labeled snapshot).
- `LatestHash()`: Returns the hash of the most recent layer, or `base` if no layers exist.
- `TruncateAfter(targetHash)`: Drops all layers after the target, used for restore to a previous point in time.

### Template Index

The file `index/templates.json` maps template names to their blob hashes:

```json
{
  "nextjs": "sha256:abc123...",
  "react-vite": "sha256:def456...",
  "python-fastapi": "sha256:ghi789..."
}
```

This index is read by `EnsureTemplate` to determine which blob to download, and updated by `UploadTemplate` after a successful upload.

## Python Integration

The Python orchestrator interacts with the storage system through several modules.

### VolumeManager

**File**: `orchestrator/app/services/volume_manager.py`

Thin client singleton. All intelligence is in the Hub. The orchestrator calls:

| Method | Hub RPC | Purpose |
|--------|---------|---------|
| `create_volume(template?, hint_node?)` | `CreateVolume` | Create a volume, optionally from template. Returns `(volume_id, node_name)`. |
| `create_empty_volume(hint_node?)` | `CreateVolume` | Convenience wrapper for blank volumes. |
| `delete_volume(volume_id)` | `DeleteVolume` | Delete from Hub, S3, and all node caches. |
| `ensure_cached(volume_id, candidate_nodes?)` | `EnsureCached` | Ensure volume on a live schedulable node. Returns node name. |
| `trigger_sync(volume_id)` | `TriggerSync` | Trigger S3 sync on the owner node. Non-blocking. |
| `volume_status(volume_id)` | `VolumeStatus` | Return ownership, cached nodes, last sync time, latest hash, layer count, and snapshots. |
| `create_service_volume(base_volume_id, service_name)` | `CreateServiceVolume` | Create ephemeral service subvolume. |

### HubClient

**File**: `orchestrator/app/services/hub_client.py`

Async gRPC client for the Volume Hub. Uses JSON codec via `content-type: application/grpc+json` metadata. Key details:

- Max message size: 64 MiB.
- Default address: `tesslate-volume-hub.kube-system.svc:9750`.
- Methods mirror the Hub RPCs with Python-native types.
- Supports async context manager for connection lifecycle.
- Default timeout: 30s for most RPCs, 120s for `EnsureCached` and `TriggerSync` (to cover network transfers).

### KubernetesOrchestrator Integration

**File**: `orchestrator/app/services/orchestration/kubernetes_orchestrator.py`

The orchestrator stores volume routing hints on the `Project` model:

- `project.volume_id`: The Hub-assigned volume ID (e.g., `vol-a1b2c3d4`).
- `project.cache_node`: Last-known compute node (hint only; Hub is the source of truth).

File operations are routed via `_get_fileops_client()`:

1. Try the cached node's FileOps (:9742) first (fast path, sub-millisecond).
2. If the node is unavailable and `volume_id` is set, call `VolumeManager.ensure_cached()` to migrate the volume to an available node, then retry.
3. All file reads/writes use the volume ID to scope operations to the correct btrfs subvolume.

### Project Model Volume Fields

**File**: `orchestrator/app/models.py`

```python
class Project(Base):
    volume_id = Column(String(255), nullable=True, index=True)
    cache_node = Column(String(255), nullable=True)
    latest_snapshot_id = Column(UUID(as_uuid=True), nullable=True)
```

## SnapshotManager (K8s VolumeSnapshot API)

**File**: `orchestrator/app/services/snapshot_manager.py`

The SnapshotManager handles Kubernetes VolumeSnapshot operations for project hibernation and versioning. It operates at the K8s API level (VolumeSnapshot CRDs) and is separate from the CAS layer-based snapshots in the btrfs CSI driver.

### Operations

| Operation | Description |
|-----------|-------------|
| `create_snapshot()` | Create a K8s VolumeSnapshot from a project's PVC. Near-instant initiation (< 1s). |
| `wait_for_snapshot_ready()` | Poll until `readyToUse: true`. **Must complete before deleting source PVC.** |
| `restore_from_snapshot()` | Create a PVC with `dataSource` pointing to a VolumeSnapshot. Uses EBS lazy loading for near-instant restore. |
| `soft_delete_project_snapshots()` | Mark snapshots as soft-deleted with configurable retention (default 30 days). |
| `cleanup_expired_snapshots()` | Delete expired soft-deleted snapshots from both K8s and database. |
| `get_project_snapshots()` | List snapshots for Timeline UI, ordered by creation date. |

### Rotation Policy

- Maximum snapshots per project: configurable (default: 5).
- Rotation preference: delete oldest hibernation snapshots first, then oldest manual snapshots.
- Always keeps at least one snapshot.

### Cross-Namespace Restore

When a project hibernates, the namespace is deleted but the VolumeSnapshotContent is retained (`deletionPolicy: Retain`). On restore:

1. Find the retained VolumeSnapshotContent by matching `volumeSnapshotRef`.
2. Extract the underlying EBS snapshot handle from `status.snapshotHandle`.
3. Create a new **pre-provisioned** VolumeSnapshotContent with the handle.
4. Create a VolumeSnapshot bound to the new content in the target namespace.
5. Create a PVC with `dataSource` referencing the VolumeSnapshot.

### ProjectSnapshot Model

```python
class ProjectSnapshot(Base):
    __tablename__ = "project_snapshots"

    id = Column(UUID, primary_key=True)
    project_id = Column(UUID, ForeignKey)
    user_id = Column(UUID, ForeignKey)
    snapshot_name = Column(String(255))       # K8s VolumeSnapshot name
    snapshot_namespace = Column(String(255))   # K8s namespace
    pvc_name = Column(String(255))            # Source PVC name
    volume_size_bytes = Column(BigInteger)     # Volume size at snapshot time
    snapshot_type = Column(String(50))         # "hibernation" or "manual"
    status = Column(String(50))               # "pending", "ready", "error", "deleted"
    label = Column(String(255))               # User-provided label
    is_latest = Column(Boolean)               # Track latest per project
    is_soft_deleted = Column(Boolean)
    soft_delete_expires_at = Column(DateTime)  # 30 days after project deletion
    created_at = Column(DateTime)
    ready_at = Column(DateTime)               # When snapshot became ready
```

## Storage Classes and Environment Differences

### StorageClasses

| StorageClass | Provisioner | Purpose | VolumeBindingMode |
|-------------|-------------|---------|-------------------|
| `tesslate-btrfs` | `btrfs.csi.tesslate.io` | Default btrfs volumes (no template) | `WaitForFirstConsumer` |
| `tesslate-btrfs-nextjs` | `btrfs.csi.tesslate.io` | Pre-templated NextJS volumes | `WaitForFirstConsumer` |
| `tesslate-block-storage` | (varies by environment) | Legacy/fallback block storage | (varies) |

Template-specific StorageClasses pass the template name as a parameter:

```yaml
parameters:
  template: "nextjs"
```

The CSI Controller reads this parameter during `CreateVolume` and clones from the named template.

### VolumeSnapshotClasses

| Class | Driver | DeletionPolicy | Used By |
|-------|--------|----------------|---------|
| `tesslate-btrfs-snapshots` | `btrfs.csi.tesslate.io` | `Delete` | btrfs CSI snapshots |
| `tesslate-ebs-snapshots` | `ebs.csi.aws.com` | `Retain` | AWS EBS snapshots (SnapshotManager) |

### Environment Configuration

| Setting | Minikube | AWS EKS |
|---------|----------|---------|
| `k8s_storage_class` | `tesslate-btrfs` | `tesslate-btrfs` |
| `k8s_snapshot_class` | `tesslate-btrfs-snapshots` | `tesslate-ebs-snapshots` |
| `template_build_storage_class` | `tesslate-btrfs` | `tesslate-btrfs` |
| `volume_hub_address` | `tesslate-volume-hub.kube-system.svc:9750` | `tesslate-volume-hub.kube-system.svc:9750` |
| `template_build_nodeops_address` | `tesslate-btrfs-csi-node-svc.kube-system.svc:9741` | `tesslate-btrfs-csi-node-svc.kube-system.svc:9741` |
| `compute_pool_namespace` | `tesslate-compute-pool` | `tesslate-compute-pool` |
| Object storage | MinIO (local S3-compatible) | AWS S3 |
| CSI node init | Loopback btrfs image (sparse, configurable size) | Loopback btrfs image on instance storage |

### CSI Node DaemonSet

The CSI node DaemonSet (`tesslate-btrfs-csi-node`) includes:

- **Init container** (`init-btrfs-pool`): Creates a sparse loopback btrfs image at `/mnt/tesslate-pool-data/pool.img` and mounts it at `/mnt/tesslate-pool` with `compress=zstd`. Skips initialization if pool is already btrfs. Default size: 50 GB (configurable via `BTRFS_POOL_SIZE_GB`).
- **Main container** (`tesslate-btrfs-csi`): Runs in `mode=node` with NodeOps (:9741), FileOps (:9742), and Drain (:9743) servers. Privileged for btrfs mount propagation.
- **Sidecar** (`csi-node-driver-registrar`): Standard CSI registrar for kubelet.

## Volume Lifecycle

### Create

```
1. Orchestrator calls VolumeManager.create_volume(template="nextjs")
2. HubClient sends CreateVolume RPC to Hub (:9750)
3. Hub generates volume ID (vol-{random hex})
4. Hub picks target node:
   a. If hint_node provided and live, use it
   b. Otherwise, pick least-loaded live node
   c. Prefer nodes that already have the template cached
5. Hub calls NodeOps.EnsureTemplate(name) on target node
   → Node downloads template from CAS if not present locally
6. Hub calls NodeOps.CreateSubvolume("volumes/vol-{id}")
   → btrfs subvolume snapshot templates/{name} volumes/vol-{id}
   (instant CoW clone, < 1ms)
7. Hub calls NodeOps.TrackVolume(volumeID, templateName, templateHash)
   → Sync daemon begins periodic sync to CAS
8. Hub registers volume in NodeRegistry (owner=targetNode, cached=[targetNode])
9. Returns (volume_id, node_name) to orchestrator
10. Orchestrator stores volume_id and cache_node on Project model
```

### Cache (EnsureCached)

```
1. Orchestrator needs to access volume (file read/write, compute start)
2. Calls VolumeManager.ensure_cached(volume_id, candidate_nodes)
3. Hub validates candidates against live node set
4. Fast path: volume already on a live candidate → return immediately
5. Peer transfer: volume on a live non-candidate → btrfs send | receive to best candidate
6. CAS restore: no live cache → replay manifest layers on best candidate
7. Returns node_name where volume is now cached
8. Orchestrator connects to node's FileOps (:9742) for file operations
```

### Sync

```
1. Sync daemon runs every 60 seconds on each node
2. For each tracked volume:
   a. Create a btrfs snapshot: snapshots/vol-{id}-{timestamp}
   b. btrfs send -p {parent snapshot} → incremental send stream
   c. Upload to CAS: tee(SHA256) → zstd → staging key → content-addressed key
   d. Append layer to volume manifest in S3
   e. Delete old local snapshots (keep latest for next incremental)
3. On-demand sync: orchestrator calls VolumeManager.trigger_sync(volume_id)
   → Hub looks up owner node → NodeOps.SyncVolume
```

### Snapshot (User-Initiated)

```
1. User creates snapshot via Timeline UI
2. Orchestrator calls Hub.CreateSnapshot(volume_id, label)
3. Hub delegates to owner node: NodeOps.CreateUserSnapshot(volumeID, label)
4. Node creates btrfs snapshot, uploads as CAS blob
5. Manifest updated with layer type="snapshot" and user label
6. Returns snapshot hash for future restore
```

### Restore

```
1. User selects snapshot from Timeline UI
2. Orchestrator calls Hub.RestoreToSnapshot(volume_id, target_hash)
3. Hub delegates to owner node: NodeOps.RestoreFromSnapshot(volumeID, targetHash)
4. Node truncates manifest after target hash
5. Replaces current volume with snapshot state
```

### Delete

```
1. Orchestrator calls VolumeManager.delete_volume(volume_id)
2. Hub calls NodeOps.UntrackVolume on owner node (stop sync daemon)
3. Hub calls NodeOps.DeleteSubvolume on all cached nodes
4. Hub calls NodeOps.DeleteVolumeCAS (delete manifest, layer snapshots)
5. Hub unregisters volume from NodeRegistry
6. Blob cleanup happens asynchronously via GC collector
```

## Configuration Reference

### Volume Hub Settings (config.py)

| Setting | Default | Description |
|---------|---------|-------------|
| `volume_hub_address` | `tesslate-volume-hub.kube-system.svc:9750` | Hub gRPC endpoint |
| `fileops_enabled` | `True` | Feature flag for v2 file operations via CSI |
| `fileops_timeout` | `30` | Default gRPC timeout for file operations (seconds) |

### Template Builder Settings (config.py)

| Setting | Default | Description |
|---------|---------|-------------|
| `template_build_enabled` | `True` | Enable template pre-building |
| `template_build_timeout` | `600` | Max seconds per template build |
| `template_build_max_retries` | `3` | Retry count for failed builds |
| `template_build_storage_class` | `tesslate-btrfs` | StorageClass for builds (must be btrfs CSI) |
| `template_build_nodeops_address` | `tesslate-btrfs-csi-node-svc.kube-system.svc:9741` | NodeOps endpoint for builds |
| `template_refresh_interval_hours` | `24` | Hours between template refreshes |
| `template_build_eager_official` | `False` | Build official templates eagerly (admin-triggered) |
| `template_build_lazy_community` | `True` | Build community templates on first use |

### Snapshot Settings (config.py)

| Setting | Default | Description |
|---------|---------|-------------|
| `k8s_snapshot_class` | `tesslate-ebs-snapshots` | K8s VolumeSnapshotClass name |
| `k8s_snapshot_retention_days` | `30` | Days to keep soft-deleted snapshots |
| `k8s_max_snapshots_per_project` | `5` | Max snapshots per project (Timeline UI) |
| `k8s_snapshot_ready_timeout_seconds` | `300` | Max wait for snapshot readiness |
| `k8s_hibernation_idle_minutes` | `10` | Hibernate pods after idle period |

### Storage Settings (config.py)

| Setting | Default | Description |
|---------|---------|-------------|
| `k8s_storage_class` | `tesslate-block-storage` | PVC StorageClass |
| `k8s_pvc_size` | `5Gi` | Default PVC size per project |
| `k8s_pvc_access_mode` | `ReadWriteOnce` | PVC access mode |
| `k8s_enable_pod_affinity` | `True` | Co-locate multi-container projects on same node |
| `k8s_affinity_topology_key` | `kubernetes.io/hostname` | Topology key for pod affinity |

### Compute Settings (config.py)

| Setting | Default | Description |
|---------|---------|-------------|
| `compute_max_concurrent_pods` | `5` | Max concurrent compute pods |
| `compute_pod_timeout` | `600` | Seconds to wait for pod readiness |
| `compute_reaper_interval_seconds` | `60` | Orphaned pod reaper interval |
| `compute_reaper_max_age_seconds` | `900` | Max pod age before reaping (15 min) |

### CSI Driver Flags (cmd/driver/main.go)

| Flag | Default | Description |
|------|---------|-------------|
| `--endpoint` | `/run/csi/socket` | CSI unix socket path |
| `--node-id` | hostname | Node identifier |
| `--pool-path` | `/mnt/tesslate-pool` | btrfs pool mount path |
| `--driver-name` | `btrfs.csi.tesslate.io` | CSI driver name |
| `--mode` | `all` | Driver mode: `node`, `hub`, or `all` |
| `--nodeops-port` | `9741` | NodeOps gRPC listen port |
| `--hub-grpc-port` | `9750` | VolumeHub gRPC listen port |
| `--storage-provider` | (none) | Object storage provider: `s3`, `gcs`, `azureblob` |
| `--storage-bucket` | (none) | Object storage bucket name |
| `--sync-interval` | `60s` | Interval between sync daemon runs |
| `--orchestrator-url` | (none) | Backend URL for GC known-volumes API |
| `--drain-port` | `9743` | HTTP port for drain endpoint |
| `--default-quota` | (none) | Default per-volume storage quota (e.g., `5Gi`) |

## Cross-References

- **Kubernetes Orchestrator**: `docs/orchestrator/orchestration/CLAUDE.md` -- container lifecycle, file operations
- **Infrastructure / Kubernetes**: `docs/infrastructure/kubernetes/CLAUDE.md` -- cluster setup, overlays
- **Database Models**: `docs/orchestrator/models/CLAUDE.md` -- Project, ProjectSnapshot models
- **System Overview**: `docs/architecture/system-overview.md` -- high-level architecture
- **Deployment Modes**: `docs/architecture/deployment-modes.md` -- Docker vs Kubernetes configuration

### Key Source Files

| File | Purpose |
|------|---------|
| `orchestrator/app/services/volume_manager.py` | VolumeManager singleton (thin Hub client) |
| `orchestrator/app/services/hub_client.py` | Async gRPC client for Volume Hub |
| `orchestrator/app/services/snapshot_manager.py` | K8s VolumeSnapshot operations |
| `orchestrator/app/services/orchestration/kubernetes_orchestrator.py` | K8s orchestrator with volume routing |
| `orchestrator/app/services/orchestration/kubernetes/helpers.py` | PVC/Deployment manifest generation |
| `orchestrator/app/services/orchestration/kubernetes/client.py` | K8s API client wrapper |
| `orchestrator/app/config.py` | All storage/volume/snapshot configuration |
| `orchestrator/app/models.py` | Project.volume_id, ProjectSnapshot model |
| `services/btrfs-csi/cmd/driver/main.go` | CSI driver entrypoint |
| `services/btrfs-csi/pkg/driver/driver.go` | Driver initialization and mode routing |
| `services/btrfs-csi/pkg/volumehub/hub.go` | VolumeStatus struct, Hub package docs |
| `services/btrfs-csi/pkg/volumehub/server.go` | VolumeHub gRPC service implementation |
| `services/btrfs-csi/pkg/volumehub/registry.go` | In-memory NodeRegistry |
| `services/btrfs-csi/pkg/volumehub/discovery.go` | NodeResolver (K8s Endpoints watch) |
| `services/btrfs-csi/pkg/cas/store.go` | CAS blob storage (SHA256, zstd, dedup) |
| `services/btrfs-csi/pkg/cas/manifest.go` | Volume manifest and layer chain |
| `services/btrfs-csi/pkg/cas/templates.go` | Template index (name to hash mapping) |
| `services/btrfs-csi/pkg/template/manager.go` | Template download/upload/ensure |
| `services/btrfs-csi/pkg/nodeops/nodeops.go` | NodeOps interface (controller-to-node delegation) |
| `services/btrfs-csi/pkg/objstore/objstore.go` | ObjectStorage interface |
| `services/btrfs-csi/pkg/objstore/rclone.go` | Rclone-based ObjectStorage implementation |
| `services/btrfs-csi/pkg/gc/collector.go` | Garbage collector for orphaned resources |
| `services/btrfs-csi/deploy/manifests/node.yaml` | CSI node DaemonSet manifest |
| `services/btrfs-csi/deploy/manifests/storage-class.yaml` | StorageClass definitions |
| `services/btrfs-csi/deploy/manifests/snapshot-class.yaml` | VolumeSnapshotClass definition |
| `services/btrfs-csi/deploy/manifests/csi-driver.yaml` | CSIDriver registration |
