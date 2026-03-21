# Kubernetes Mode - Production Container Orchestration

**File**: `orchestrator/app/services/orchestration/kubernetes_orchestrator.py`

Kubernetes mode provides production-grade container orchestration with namespace isolation, Hub-based volume management (btrfs CSI), and secure multi-tenancy. Each user project gets its own Kubernetes namespace with a btrfs subvolume managed by the Volume Hub, network policies, and HTTPS ingress.

## Overview

Kubernetes mode is designed for **production deployment** at scale. It supports thousands of concurrent projects with Hub-coordinated volume caching, btrfs-based hibernation with S3 sync, resource management, and horizontal scaling of the orchestrator backend.

**Key Features**:
- **Namespace per project** pattern for complete isolation
- **Volume Hub** — storageless gRPC orchestrator that coordinates btrfs subvolumes, node placement, cache migration, and S3 sync across compute nodes
- **btrfs CSI driver** — PV/PVC backed by local btrfs subvolumes on compute nodes; instant snapshot-cloning for templates
- **ComputeManager** — two-tier compute: Tier 1 (ephemeral pods for one-off commands) and Tier 2 (full dev environments with services)
- **VolumeManager** — thin client wrapper over Hub gRPC for volume lifecycle (create, delete, ensure_cached, trigger_sync)
- **FileOps** — gRPC service on each compute node for direct local file I/O (~0.01ms); used for read/write/list/grep/glob
- **Hibernation** via `ComputeManager.stop_environment()` + `VolumeManager.trigger_sync()` (btrfs subvolumes persist on node, S3 for durability)
- **Pod affinity** for shared RWO storage (multi-container projects)
- **NetworkPolicy** for strict network isolation
- **Timeline UI** — up to 5 snapshots per project for version history (legacy VolumeSnapshot path)
- **Database-based activity tracking** (survives backend restarts)

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                   Tesslate Namespace                          │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Backend Pod (KubernetesOrchestrator + ComputeManager) │  │
│  │  - Manages all project namespaces                      │  │
│  │  - Routes file I/O via FileOps gRPC to compute nodes   │  │
│  │  - Volume lifecycle via VolumeManager → Hub gRPC       │  │
│  │  - Hibernation via stop_environment + S3 sync           │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
            │                           │
            │  Hub gRPC :9750           │  FileOps gRPC :9742
            ▼                           ▼
┌──────────────────┐    ┌───────────────────────────────────┐
│  Volume Hub      │    │  Compute Node (btrfs pool)        │
│  (kube-system)   │    │  /mnt/tesslate-pool/volumes/      │
│  - Volume CRUD   │    │    ├── vol-abc123/  (project A)   │
│  - Cache routing │    │    ├── vol-def456/  (project B)   │
│  - S3 sync coord │    │    └── vol-abc123-postgres/       │
│  - Node liveness │    │  FileOps daemon :9742             │
└──────────────────┘    │  btrfs CSI driver                 │
                        └───────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
                    ▼               ▼               ▼
          ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
          │ proj-{uuid-1}  │ │ proj-{uuid-2}  │ │ proj-{uuid-3}  │
          │ ┌────────────┐ │ │ ┌────────────┐ │ │ (hibernated)   │
          │ │ CSI PV+PVC │ │ │ │ CSI PV+PVC │ │ │                │
          │ │ btrfs vol  │ │ │ │ btrfs vol  │ │ │ [namespace     │
          │ │ /app       │ │ │ │ /app       │ │ │  deleted]      │
          │ └────────────┘ │ │ └────────────┘ │ │                │
          │       ▲        │ │       ▲        │ │ [btrfs subvol  │
          │       │ mounts │ │       │ mounts │ │  on node]      │
          │ ┌─────┴──────┐ │ │ ┌─────┴──────┐ │ │       ▼       │
          │ │ Dev: FE    │ │ │ │ Dev: FE    │ │ │ ┌──────────┐  │
          │ │ (on start) │ │ │ │ (on start) │ │ │ │ S3 sync  │  │
          │ └────────────┘ │ │ └────────────┘ │ │ │ (backup) │  │
          │ ┌────────────┐ │ │ ┌────────────┐ │ │ └──────────┘  │
          │ │ Dev: BE    │ │ │ │ Svc: DB    │ │ └────────────────┘
          │ │ (on start) │ │ │ │ (service)  │ │
          │ └────────────┘ │ │ └────────────┘ │
          │                │ │                │
          │ NetworkPolicy  │ │ NetworkPolicy  │
          │ Ingress (TLS)  │ │ Ingress (TLS)  │
          └────────────────┘ └────────────────┘
```

## Key Concepts

### 1. Namespace Per Project

Each project gets a dedicated Kubernetes namespace: `proj-{project-uuid}`

**Example**: Project ID `d4f6e8a2-...` -> Namespace `proj-d4f6e8a2-e89b-12d3-a456-426614174000`

**Benefits**:
- Complete isolation (cannot access other projects)
- Resource quotas per project
- Easy cleanup (delete namespace = delete all resources)
- NetworkPolicy scoped to namespace

### 2. Volume Hub Architecture

All volume intelligence lives in the **Volume Hub** -- a storageless gRPC orchestrator in `kube-system` that coordinates compute nodes for volume lifecycle, cache placement, and S3 sync.

**Components**:

| Component | Location | Purpose |
|-----------|----------|---------|
| **Volume Hub** | `kube-system:9750` | gRPC orchestrator: volume CRUD, cache routing, S3 sync coordination, node liveness |
| **VolumeManager** | `services/volume_manager.py` | Thin Python client wrapping Hub gRPC calls |
| **HubClient** | `services/hub_client.py` | Async gRPC client (JSON codec over `application/grpc+json`) |
| **FileOps** | Each compute node `:9742` | Local btrfs file I/O (~0.01ms): read, write, list, tree, delete |
| **FileOpsClient** | `services/fileops_client.py` | Async gRPC client for FileOps on compute nodes |
| **NodeDiscovery** | `services/node_discovery.py` | Resolves compute node names to FileOps gRPC addresses |
| **btrfs CSI driver** | Each compute node | CSI driver that mounts btrfs subvolumes into pods via PV/PVC |

**Volume lifecycle**:
```
1. Project created → VolumeManager.create_volume(template="nextjs")
   → Hub creates btrfs subvolume on best node (template clone = instant)
   → Returns (volume_id, node_name)
   → Stored on Project model: project.volume_id, project.cache_node

2. Project started → VolumeManager.ensure_cached(volume_id, candidate_nodes)
   → Hub validates candidates against live node set
   → If volume is already on a live candidate, returns immediately
   → Otherwise, peer-transfers or restores from CAS to best candidate
   → Returns node_name

3. File operations → FileOpsClient connects to node's :9742
   → Direct local btrfs I/O, no pod exec
   → Fallback: if node is unavailable, ensure_cached migrates to a new node

4. Project hibernated → ComputeManager.stop_environment() (deletes namespace + PVs)
   → VolumeManager.trigger_sync() pushes btrfs subvolume to S3 for durability
```

### 3. ComputeManager (Two-Tier Compute)

The `ComputeManager` (`services/compute_manager.py`) handles all container lifecycle through two tiers:

**Tier 1 (Ephemeral Pods)**: Short-lived pods in a dedicated `tesslate-compute-pool` namespace for one-off commands (e.g., `npm install`, git operations). Self-destruct after completion. PSA `restricted` enforced.

**Tier 2 (Full Environments)**: Persistent dev environments with dev servers, service containers, ingress routing, and preview URLs. Created in per-project namespaces (`proj-{uuid}`).

**Key methods**:
- `run_command(volume_id, node_name, command, timeout=120, image=None) -> tuple[str, int, str]` -- Tier 1: ephemeral pod for a single command; returns `(output, exit_code, pod_name)`
- `start_environment(project, containers, connections, user_id, db)` -- Tier 2: full environment with all containers
- `stop_environment(project, db)` -- Tier 2: delete namespace + PVs (btrfs subvolumes stay on node)

### 4. Lifecycle Separation

**CRITICAL**: The architecture separates three distinct lifecycles:

```
VOLUME LIFECYCLE:
  1. Project created → Hub creates btrfs subvolume (from template or empty)
  2. Volume persists across start/stop cycles (btrfs subvolumes are durable)
  3. S3 sync for durability (Hub-coordinated)
  4. Volume deleted only on permanent project deletion

CONTAINER LIFECYCLE:
  1. User clicks "Start" → ComputeManager.start_environment()
     - ensure_cached: Hub validates volume is on a schedulable node
     - Create namespace + PV/PVC + Deployments + Services + Ingress
  2. User clicks "Stop" → ComputeManager.stop_environment()
     - Delete namespace + PVs (btrfs subvolumes untouched)

FILE LIFECYCLE:
  1. File reads/writes via FileOps gRPC directly to compute node
  2. No pod exec required for file operations
  3. Files persist on btrfs subvolume independent of pod lifecycle

HIBERNATION LIFECYCLE:
  1. User leaves or idle timeout → hibernate_project_bg()
  2. ComputeManager.stop_environment() → delete namespace + PVs
  3. VolumeManager.trigger_sync() → push btrfs subvolume to S3
  4. btrfs subvolume persists on compute node for fast restart
  5. User returns → ensure_cached + start_environment() (no restore needed if node is live)
```

### 5. File-Manager Pod (Legacy Path)

The file-manager pod is used by `ensure_project_environment()` for legacy project initialization. It:

- Handles `git clone` when containers are added to the architecture graph
- Provides pod-exec-based file operations when FileOps is unavailable
- Keeps PVC mounted (prevents unbound state)

**Specification**:
- Image: `tesslate-devserver:latest` (same as dev containers)
- Command: `tail -f /dev/null` (keep alive)
- Volume: PVC mounted at `/app`
- Resources: 256Mi-1536Mi RAM
- No pod affinity (anchor pod -- dev containers co-locate with it)

**Note**: For projects using the volume-first path (Hub/btrfs), file operations go through FileOps gRPC instead of pod exec, and the file-manager pod is not required.

### 6. Dev Container Pods

Dev containers are created by `ComputeManager.start_environment()`:

**Lifecycle**:
1. User clicks "Start" in UI
2. Backend calls `start_container()` -> delegates to `ComputeManager.start_environment()`
3. Hub ensures volume is cached on a schedulable node
4. CSI PV+PVC created pointing to btrfs subvolume
5. Deployment + Service + Ingress created
6. Startup command runs in tmux session
7. URL becomes accessible: `{protocol}://{slug}-{container}.{domain}`

**Startup/Probe Strategy**:
- Startup probe: exec-based (`tmux has-session -t main`), passes fast even if dev server fails
- Readiness probe: HTTP GET on port (controls traffic routing only)
- Liveness probe: exec-based (`tmux has-session -t main`), keeps container alive
- This allows the agent to fix startup failures without pod restarts

### 7. EBS VolumeSnapshot Pattern (Legacy -- not used in current hibernation flow)

> **Note**: The VolumeSnapshot methods (`_save_to_snapshot`, `_restore_from_snapshot`, `_get_hibernation_pvc_names`) still exist in `kubernetes_orchestrator.py` and are called by the legacy `delete_project_environment(save_snapshot=True)` / `ensure_project_environment(is_hibernated=True)` code paths. However, the **active hibernation flow** (`hibernate_project_bg()` in `services/hibernate.py`) does **not** use VolumeSnapshots. It calls `ComputeManager.stop_environment()` (deletes namespace + PVs) followed by `VolumeManager.trigger_sync()` (pushes btrfs subvolume to S3).

The legacy VolumeSnapshot pattern was designed to hibernate idle projects using EBS snapshots:

```python
# Legacy PVC Discovery (_get_hibernation_pvc_names)
# Lists all PVCs in namespace, returns project-storage + any service PVCs
# (labeled tesslate.io/component=service-storage or prefixed svc-)

# Legacy Hibernation (_save_to_snapshot, via SnapshotManager)
1. Discover all PVCs via _get_hibernation_pvc_names(namespace)
2. Skip snapshot ONLY if project is NOT initialized AND there are no service PVCs
3. For each PVC, create VolumeSnapshot and wait for readyToUse (timeout: 300s)
4. Delete namespace (cascades to all PVCs, pods, services, ingresses)
5. Create ProjectSnapshot database record per PVC, update project status

# Legacy Restoration (_restore_from_snapshot, via SnapshotManager)
1. Restore project-storage PVC first (if snapshot exists)
2. Query get_latest_ready_snapshots_by_pvc() for service PVC snapshots
3. Iterate and restore each service PVC from its snapshot
4. EBS provisioner creates new volumes from snapshots (lazy-load)
5. Create namespace, pods mount restored PVCs
6. Update project status to 'active'
```

### 8. Pod Affinity (Multi-Container Projects)

For projects with multiple containers (frontend + backend), all pods must run on the same node:

**Reason**: PVC uses `ReadWriteOnce` (RWO) access mode, which can only be mounted by pods on the same node. Additionally, btrfs subvolumes are node-local.

**Implementation**:
```python
# In helpers.py
affinity = client.V1Affinity(
    pod_affinity=client.V1PodAffinity(
        required_during_scheduling_ignored_during_execution=[
            client.V1PodAffinityTerm(
                label_selector=client.V1LabelSelector(
                    match_labels={"tesslate.io/project-id": str(project_id)}
                ),
                topology_key="kubernetes.io/hostname"
            )
        ]
    )
)
```

**Note**: The file-manager pod (when used) is the anchor pod that schedules freely. Dev containers use pod affinity to co-locate WITH the file-manager. Giving file-manager affinity causes deadlock.

## Project Lifecycle

### Starting a Project (via ComputeManager)

```python
result = await orchestrator.start_project(
    project, containers, connections, user_id, db
)
# Delegates to ComputeManager.start_environment()
```

**Steps** (in `ComputeManager.start_environment()`):
1. **Ensure volume cached**: `VolumeManager.ensure_cached(volume_id, candidate_nodes)` -- Hub validates candidates against live node set and picks the best one
2. **Update cache_node**: If the node changed, persist `project.cache_node` to DB
3. **Separate containers**: Split into `service_containers` and `dev_containers`
4. **Create namespace**: `proj-{uuid}` with PSA `baseline` enforcement
5. **Apply NetworkPolicy**: Project isolation rules
6. **Copy TLS secret**: Wildcard cert for HTTPS ingress (if configured)
7. **Create project PV+PVC**: CSI-backed static PV pointing to btrfs subvolume; PVC `project-source` binds to it
8. **Deploy service containers** (e.g., Postgres):
   - Create service subvolume via `VolumeManager.create_service_volume()`
   - Create service PV+PVC for persistent data (PVC name: `svc-{dir}-data`)
   - Create Deployment with service image + ClusterIP Service for internal DNS
9. **Deploy dev containers** (e.g., Next.js):
   - Resolve startup command + port from `Container` model
   - Build env overrides (sibling container URLs for service discovery)
   - Create Deployment (mounts `project-source` PVC) + Service + Ingress
10. **Verify pods**: Poll for 30s to ensure at least one dev pod is running
11. **Update project state**: `compute_tier = "environment"`, `environment_status = "active"`
12. **Send WebSocket progress**: Updates sent to frontend during each phase

**Returns**: `{container_directory: preview_url}`

### Stopping a Project

```python
await orchestrator.stop_project(project_slug, project_id, user_id)
# Delegates to ComputeManager.stop_environment()
```

**Steps** (in `ComputeManager.stop_environment()`):
1. **Delete namespace**: Cascades to all namespace-scoped resources (PVCs, deployments, services, ingress)
2. **Delete cluster-scoped PVs**: Filtered by `tesslate.io/project-id` label. Retain policy keeps btrfs subvolumes intact on the node.
3. **Update project state**: `compute_tier = "none"`

**Important**: btrfs subvolumes persist on the compute node. Only K8s resources are cleaned up.

### Starting a Single Container

```python
result = await orchestrator.start_container(
    project, container, all_containers, connections, user_id, db
)
```

Delegates to `ComputeManager.start_environment()` which deploys the full environment (all containers). Returns the URL for the requested container.

### Stopping a Single Container

```python
await orchestrator.stop_container(
    project_slug, project_id, container_name, user_id,
    container_type="base",  # or "service"
    service_slug=None,
)
```

**Steps**:
- **Base containers**: Delete `dev-{dir}` Deployment + Service + Ingress
- **Service containers**: Delete `svc-{slug}` Deployment + Service (no Ingress)

**Important**: Files persist on btrfs subvolume. Only the running pod is stopped.

### Ensuring Legacy Environment (File-Manager Path)

```python
namespace = await orchestrator.ensure_project_environment(
    project_id, user_id, is_hibernated=False, db=db
)
```

**Steps**:
1. **Create namespace**: `proj-{uuid}` with labels
2. **Create NetworkPolicy**: Isolate project from other namespaces
3. **Create PVC**: `project-storage` (from snapshot if hibernated, otherwise empty)
4. **Copy TLS secret**: For HTTPS ingress (wildcard cert)
5. **Create file-manager deployment**: Always-running pod
6. **Wait for ready**: File-manager must be ready before returning

### Hibernating a Project

The active hibernation entry point is `hibernate_project_bg()` in `services/hibernate.py`. There is no `orchestrator.hibernate_project()` method.

```python
# Called as a background task (asyncio.create_task)
await hibernate_project_bg(project_id, user_id)
```

**Steps** (in `hibernate_project_bg()`):
1. **Stop compute**: `ComputeManager.stop_environment(project, db)` -- deletes namespace + cluster-scoped PVs (btrfs subvolumes stay on node)
2. **Sync to S3**: `VolumeManager.trigger_sync(volume_id)` -- pushes btrfs subvolume to S3 via the Volume Hub
3. **Update database**: `environment_status = 'hibernated'`, `hibernated_at = now()`
4. **WebSocket notifications**: Sends `environment_stopping` and `environment_stopped` events

**Important**: No EBS VolumeSnapshots are created during hibernation. The btrfs subvolume persists on the compute node, and S3 sync provides durability. See section 7 below for the legacy VolumeSnapshot code path.

**Safety**: If any step fails, `environment_status` is set to `'stopped'` (not `'hibernated'`).

### Deleting a Project (Permanent)

```python
await orchestrator.delete_project_namespace(project_id, user_id)
```

**Steps**:
1. Check if namespace exists
2. Delete namespace (cascades all resources)

## File Operations (via FileOps gRPC)

All file operations route through the FileOps gRPC service running on compute nodes. The orchestrator looks up the project's `volume_id` and `cache_node` from the database, connects to the node's FileOps at `:9742`, and performs direct local btrfs I/O.

**Routing logic** (`_get_fileops_client`):
1. Try connecting to `cache_node`'s FileOps directly (fast path)
2. If node is unavailable and a `volume_id` is provided, call `VolumeManager.ensure_cached()` to migrate the volume to a live node, then connect to the new node

### Reading a File

```python
content = await orchestrator.read_file(
    user_id, project_id, container_name, file_path, subdir="frontend"
)
```

**Implementation**:
```python
volume_id, cache_node = await self._get_project_volume_info(project_id)
vol_path = self._build_volume_path(file_path, subdir)
async with await self._get_fileops_client(cache_node, volume_id) as client:
    return await client.read_file_text(volume_id, vol_path)
```

### Writing a File

```python
success = await orchestrator.write_file(
    user_id, project_id, container_name, file_path, content, subdir="frontend"
)
```

### Listing Files / Tree

```python
files = await orchestrator.list_files(user_id, project_id, container_name, directory=".")
tree = await orchestrator.list_tree(user_id, project_id, container_name, subdir="frontend")
```

`list_tree` uses the FileOps `ListTree` RPC with server-side filtering (exclude `node_modules`, `.git`, binary files, etc.).

### Glob / Grep

```python
matches = await orchestrator.glob_files(user_id, project_id, container_name, pattern="*.tsx")
results = await orchestrator.grep_files(user_id, project_id, container_name, pattern="useState")
```

### Path Safety

Both `_build_pod_path()` and `_build_volume_path()` normalize paths and enforce containment:
- Absolute anchor prevents traversal attacks (`../../../etc/passwd`)
- `subdir="."` is treated as no subdir
- Raises `ValueError` if resolved path escapes boundary

## Shell Execution

Execute commands in the file-manager pod (or dev container as fallback):

```python
output = await orchestrator.execute_command(
    user_id, project_id, container_name,
    command=["npm", "install", "axios"],
    timeout=300,
    working_dir="frontend"
)
```

**Implementation**: Tries file-manager pod first via `_exec_in_pod`, falls back to dev container via `execute_command_in_pod`. For Tier 1 compute (one-off commands), `ComputeManager.run_command()` uses ephemeral pods with volume locality.

## Networking

### Ingress Routing

Each dev container gets an NGINX Ingress:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: dev-frontend
  namespace: proj-d4f6e8a2-...
  annotations:
    nginx.ingress.kubernetes.io/proxy-http-version: "1.1"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
spec:
  ingressClassName: nginx
  rules:
    - host: my-app-abc123-frontend.your-domain.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: dev-frontend
                port:
                  number: 3000
  tls:
    - hosts:
        - my-app-abc123-frontend.your-domain.com
      secretName: tesslate-wildcard-tls
```

**URL Pattern**: `{protocol}://{project-slug}-{container-directory}.{domain}`

**TLS**: Uses wildcard certificate copied to project namespace. Protocol is `https` if `k8s_wildcard_tls_secret` is configured, otherwise `http`.

### Service Containers (Internal DNS)

Service containers (e.g., Postgres) get ClusterIP services for internal DNS:
- Deployment name: `svc-{service-slug}`
- Service name: `svc-{service-slug}`
- No Ingress (internal-only)
- DNS: `svc-{slug}.proj-{uuid}.svc.cluster.local`

### NetworkPolicy (Isolation)

Each project namespace gets a NetworkPolicy:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: project-isolation
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
  ingress:
    - from: [{namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: ingress-nginx}}}]
    - from: [{namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: tesslate}}}]
    - from: [{podSelector: {}}]  # Same namespace
  egress:
    - to: [{namespaceSelector: {}}]  # DNS
      ports: [{protocol: UDP, port: 53}]
    - ports: [{protocol: TCP, port: 443}, {protocol: TCP, port: 80}]  # HTTPS/HTTP
```

**Effect**:
- Ingress from NGINX (public access to dev servers)
- Ingress from Tesslate backend (file operations)
- Ingress within namespace (frontend -> backend, app -> Postgres)
- Egress to DNS, HTTP/HTTPS (npm install, git clone, external APIs)
- No ingress from other projects
- No egress to internal cluster services (unless explicitly allowed)

## Activity Tracking & Cleanup

### Database-Based Tracking

Activity tracking is database-based (supports horizontal scaling):

```python
from orchestrator.app.services.activity_tracker import track_project_activity
await track_project_activity(db, project_id, user_id)
# Updates: Project.last_activity = now()
```

The `KubernetesOrchestrator.track_activity()` method is a deprecated no-op retained for interface compatibility.

### Cleanup Cronjobs

**Hibernation CronJob**: Runs periodically, finds projects where `last_activity < cutoff_time` and `environment_status = 'active'`, hibernates them via `hibernate_project_bg()`.

**Snapshot Cleanup CronJob**: Daily at 3 AM UTC, deletes expired snapshots after 30-day retention period.

**WebSocket Notification**: When hibernating, the backend sends a WebSocket message to redirect the user:
```json
{
  "environment_status": "hibernating",
  "message": "Saving project files...",
  "action": "redirect_to_projects"
}
```

## Configuration

Key environment variables (see `orchestrator/app/config.py`):

```bash
# Deployment mode
DEPLOYMENT_MODE=kubernetes

# Image configuration
K8S_DEVSERVER_IMAGE=registry.digitalocean.com/.../tesslate-devserver:latest
K8S_IMAGE_PULL_POLICY=IfNotPresent
K8S_IMAGE_PULL_SECRET=tesslate-container-registry-nyc3

# Storage
K8S_STORAGE_CLASS=tesslate-block-storage
K8S_PVC_SIZE=5Gi
K8S_PVC_ACCESS_MODE=ReadWriteOnce

# Snapshots
K8S_SNAPSHOT_CLASS=tesslate-ebs-snapshots
K8S_SNAPSHOT_RETENTION_DAYS=30
K8S_MAX_SNAPSHOTS_PER_PROJECT=5
K8S_SNAPSHOT_READY_TIMEOUT_SECONDS=300
K8S_HIBERNATION_IDLE_MINUTES=10

# Pod affinity
K8S_ENABLE_POD_AFFINITY=true
K8S_AFFINITY_TOPOLOGY_KEY=kubernetes.io/hostname

# Namespace & network
K8S_NAMESPACE_PER_PROJECT=true
K8S_ENABLE_NETWORK_POLICIES=true
K8S_INGRESS_CLASS=nginx

# TLS
K8S_WILDCARD_TLS_SECRET=tesslate-wildcard-tls

# Namespace configuration
K8S_DEFAULT_NAMESPACE=tesslate
COMPUTE_POOL_NAMESPACE=tesslate-compute-pool

# Volume Hub
VOLUME_HUB_ADDRESS=tesslate-volume-hub.kube-system.svc:9750

# FileOps
FILEOPS_ENABLED=true
FILEOPS_TIMEOUT=30

# Compute
COMPUTE_MAX_CONCURRENT_PODS=5
COMPUTE_POD_TIMEOUT=600
COMPUTE_REAPER_INTERVAL_SECONDS=60
COMPUTE_REAPER_MAX_AGE_SECONDS=900

# Template Builder
TEMPLATE_BUILD_ENABLED=true
TEMPLATE_BUILD_STORAGE_CLASS=tesslate-btrfs
TEMPLATE_BUILD_NODEOPS_ADDRESS=tesslate-btrfs-csi-node-svc.kube-system.svc:9741
```

## Debugging

### Check Project Namespace

```bash
PROJECT_ID="d4f6e8a2-..."
NAMESPACE="proj-$PROJECT_ID"

kubectl get all -n $NAMESPACE
```

### File-Manager Logs

```bash
kubectl logs -n $NAMESPACE deployment/file-manager -c file-manager
```

### Dev Container Logs

```bash
kubectl logs -n $NAMESPACE deployment/dev-frontend -c dev-server
```

### Exec into File-Manager

```bash
kubectl exec -n $NAMESPACE deployment/file-manager -c file-manager -- ls -la /app
```

### Check Ingress

```bash
kubectl get ingress -n $NAMESPACE
kubectl describe ingress dev-frontend -n $NAMESPACE
```

### Check PVCs

```bash
kubectl get pvc -n $NAMESPACE
kubectl get pv -l tesslate.io/project-id=$PROJECT_ID
```

### Check Volume Hub

```bash
# Hub logs
kubectl logs -n kube-system deployment/tesslate-volume-hub

# Check volume status (via grpcurl)
grpcurl -plaintext tesslate-volume-hub.kube-system.svc:9750 \
  volumehub.VolumeHub/VolumeStatus \
  -d '{"volume_id": "vol-abc123"}'
```

### Check Compute Pool

```bash
# List ephemeral compute pods
kubectl get pods -n tesslate-compute-pool -l tesslate.io/tier=1

# Check resource quota
kubectl describe resourcequota -n tesslate-compute-pool
```

### Check NetworkPolicy

```bash
kubectl get networkpolicy -n $NAMESPACE
kubectl describe networkpolicy project-isolation -n $NAMESPACE
```

## Common Issues

### ImagePullBackOff

**Problem**: Pod stuck in `ImagePullBackOff`

**Cause**: Image not available in registry

**Solutions**:
- **Minikube**: `minikube -p tesslate image load tesslate-devserver:latest`
- **EKS**: Check ECR credentials, ensure image is pushed to `<AWS_ACCOUNT_ID>.dkr.ecr...`

### Volume Mount Errors

**Problem**: Pod stuck in `Pending` with volume mount errors

**Cause**: PV node affinity mismatch or btrfs subvolume not cached on target node

**Solution**: Check that `project.cache_node` matches the PV's node affinity. The Hub's `ensure_cached` should handle migration automatically.

### 503 Service Unavailable

**Problem**: Ingress returns 503

**Causes**:
1. Pod not ready (tmux startup probe passed but readiness probe failing)
2. Service selector doesn't match pod labels
3. NGINX ingress controller not finding endpoints

**Debug**:
```bash
kubectl get pods -n $NAMESPACE
kubectl get endpoints -n $NAMESPACE
kubectl logs -n ingress-nginx deployment/ingress-nginx-controller
```

### Snapshot Hibernation Failures (Legacy)

> **Note**: These commands apply to the legacy VolumeSnapshot code path (`delete_project_environment(save_snapshot=True)`), which is not used by the current hibernation flow. See section 7 for details.

**Problem**: Legacy hibernation fails with "snapshot not ready"

**Debug**:
```bash
kubectl logs -n tesslate deployment/tesslate-backend
kubectl get volumesnapshot -n proj-<uuid>
kubectl describe volumesnapshot <name> -n proj-<uuid>
kubectl logs -n kube-system -l app=snapshot-controller
```

### ComputeQuotaExceeded

**Problem**: `ComputeQuotaExceeded` error when running commands

**Cause**: Concurrent Tier 1 pod limit reached (`COMPUTE_MAX_CONCURRENT_PODS`)

**Solution**: Wait for current pods to complete, or increase the limit. Check for orphaned pods:
```bash
kubectl get pods -n tesslate-compute-pool -l tesslate.io/tier=1
```

### FileOps Unavailable

**Problem**: File operations fail with gRPC errors

**Cause**: Compute node's FileOps daemon not reachable

**Solution**: The orchestrator automatically calls `ensure_cached` to migrate the volume to an available node. Check node health:
```bash
kubectl get nodes
kubectl describe node <node-name>
```

## Advantages & Limitations

### Advantages

- **Scalable**: Thousands of projects, horizontal scaling of backend
- **Cost-efficient**: Hibernation saves compute; btrfs subvolumes are lightweight
- **Fast file I/O**: FileOps gRPC on local btrfs (~0.01ms per operation)
- **Instant templates**: btrfs snapshot-clone for project creation
- **Isolated**: Namespace + NetworkPolicy = strong multi-tenancy
- **Fast restore**: Near-instant restart when btrfs subvolume is still cached on node
- **Resilient**: Database-based tracking, survives backend restarts
- **Timeline UI**: Up to 5 snapshots per project for version history
- **Recovery**: 30-day soft delete retention for accidental deletions

### Limitations

- **Node locality**: btrfs subvolumes are node-local; migration requires Hub coordination
- **Pod scheduling**: Container startup depends on K8s scheduler + volume locality
- **RWO constraint**: Multi-container projects need pod affinity (same node)
- **Hub dependency**: Volume Hub must be healthy for volume operations

## Next Steps

- See [kubernetes-client.md](./kubernetes-client.md) for K8s API wrapper details
- See [kubernetes-helpers.md](./kubernetes-helpers.md) for manifest generation
- Compare with [docker-mode.md](./docker-mode.md) for local development
