# Kubernetes Mode - Production Container Orchestration

**File**: `orchestrator/app/services/orchestration/kubernetes_orchestrator.py`

Kubernetes mode provides production-grade container orchestration with namespace isolation, EBS VolumeSnapshot hibernation, and secure multi-tenancy. Each user project gets its own Kubernetes namespace with persistent storage, network policies, and HTTPS ingress.

## Overview

Kubernetes mode is designed for **production deployment** at scale. It supports thousands of concurrent projects with automatic hibernation, resource management, and horizontal scaling of the orchestrator backend.

**Key Features**:
- **Namespace per project** pattern for complete isolation
- **File-manager pod** + **dev container pods** (separate lifecycles)
- **EBS VolumeSnapshot** for hibernation/restoration (instant restore, deps auto-installed on first boot)
- **Pod affinity** for shared RWO storage (multi-container projects)
- **NetworkPolicy** for strict network isolation
- **Timeline UI** - up to 5 snapshots per project for version history
- **Database-based activity tracking** (survives backend restarts)

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                   Tesslate Namespace                         │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Backend Pod (KubernetesOrchestrator)                  │  │
│  │  - Manages all project namespaces                      │  │
│  │  - Creates/restores VolumeSnapshots                    │  │
│  │  - Streams files to/from pods securely                 │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
                         │
            ┌────────────┼────────────┐
            │            │            │
            ▼            ▼            ▼
┌────────────────┐ ┌────────────────┐ ┌────────────────┐
│ proj-{uuid-1}  │ │ proj-{uuid-2}  │ │ proj-{uuid-3}  │
│ ┌────────────┐ │ │ ┌────────────┐ │ │ (hibernated)   │
│ │ PVC        │ │ │ │ PVC        │ │ │                │
│ │ 10Gi RWO   │ │ │ │ 10Gi RWO   │ │ │   [deleted]    │
│ │ /app       │ │ │ │ /app       │ │ │                │
│ └────────────┘ │ │ └────────────┘ │ │ [VolumeSnapshot│
│       ▲        │ │       ▲        │ │  preserved]    │
│       │ mounts │ │       │ mounts │ │       ▼        │
│       │        │ │       │        │ │  ┌──────────┐  │
│ ┌─────┴──────┐ │ │ ┌─────┴──────┐ │ │  │ EBS      │  │
│ │ File Mgr   │ │ │ │ File Mgr   │ │ │  │ Snapshot │  │
│ │ (always)   │ │ │ │ (always)   │ │ │  └──────────┘  │
│ └────────────┘ │ │ └────────────┘ │ └────────────────┘
│ ┌────────────┐ │ │ ┌────────────┐ │
│ │ Dev: FE    │ │ │ │ Dev: FE    │ │
│ │ (on start) │ │ │ │ (on start) │ │
│ └────────────┘ │ │ └────────────┘ │
│ ┌────────────┐ │ │ ┌────────────┐ │
│ │ Dev: BE    │ │ │ │ Dev: DB    │ │
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

**Example**: Project ID `d4f6e8a2-...` → Namespace `proj-d4f6e8a2-e89b-12d3-a456-426614174000`

**Benefits**:
- ✅ Complete isolation (cannot access other projects)
- ✅ Resource quotas per project
- ✅ Easy cleanup (delete namespace = delete all resources)
- ✅ NetworkPolicy scoped to namespace

### 2. Lifecycle Separation

**CRITICAL**: The new architecture separates three distinct lifecycles:

```
FILE LIFECYCLE:
  1. User opens project → create namespace + PVC + file-manager pod
  2. User adds container → file-manager runs `git clone` to /app/{subdir}/
  3. Files persist on PVC

CONTAINER LIFECYCLE:
  1. User clicks "Start" → create Deployment + Service + Ingress
  2. Dev container mounts existing PVC (files already present!)
  3. No init containers needed
  4. User clicks "Stop" → delete Deployment (files persist)

SNAPSHOT LIFECYCLE (Hibernation):
  1. User leaves or idle timeout → discover all PVCs via _get_hibernation_pvc_names()
     (project-storage + service PVCs labeled tesslate.io/component=service-storage or prefixed svc-)
  2. Create VolumeSnapshot for each PVC, wait for readyToUse on each (timeout: 300s)
  3. Delete namespace (including all PVCs)
  4. User returns → restore project-storage PVC first, then iterate service PVC snapshots
  5. EBS lazy-loads data on first access (near-instant restore)
```

**Why this matters**: EBS VolumeSnapshots preserve the entire filesystem state including node_modules. No npm install needed on restore - the project is ready in seconds.

### 3. File-Manager Pod

The file-manager pod is **always running** while a project is open (user is viewing it in the builder):

**Purpose**:
- Handle file operations (read/write) when dev containers aren't running
- Execute `git clone` when containers are added to the architecture graph
- Keep PVC mounted (prevents unbound state)
- Provide consistent file access regardless of dev container state

**Specification**:
- Image: `tesslate-devserver:latest` (same as dev containers)
- Command: `tail -f /dev/null` (keep alive)
- Volume: PVC mounted at `/app`
- Resources: 256Mi-1536Mi RAM (enough for npm install)

### 4. Dev Container Pods

Dev containers are created **on-demand** when the user clicks "Start":

**Lifecycle**:
1. User clicks "Start" in UI
2. Backend calls `orchestrator.start_container(...)`
3. Deployment + Service + Ingress created
4. Pod mounts existing PVC (files already cloned by file-manager)
5. Startup command runs in tmux session: `npm run dev`
6. Startup/readiness/liveness probes wait for server
7. URL becomes accessible: `https://{slug}-{container}.your-domain.com`

**Key difference from file-manager**: Dev containers run the actual dev server (Next.js, Express, etc.) while file-manager just keeps the filesystem alive.

### 5. EBS VolumeSnapshot Pattern

The EBS VolumeSnapshot pattern hibernates idle projects to save resources:

```
┌─────────────────────────────────────────────────────────────┐
│                  ACTIVE STATE                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ Namespace: proj-{uuid}                                │  │
│  │ ├── PVC (10Gi EBS)                                    │  │
│  │ ├── File-manager pod                                  │  │
│  │ └── Dev container pods (if started)                   │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                         │
                         │ Idle 30+ minutes
                         ▼
            ┌─────────────────────────────┐
            │ HIBERNATION (Snapshot)      │
            │                             │
            │ 1. Create VolumeSnapshot    │
            │ 2. Wait for readyToUse      │
            │ 3. Delete namespace         │
            │                             │
            │ (< 5 seconds total!)        │
            └─────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  HIBERNATED STATE                           │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ VolumeSnapshot: snap-{project_id}-{timestamp}         │  │
│  │ (Full EBS volume state, including node_modules!)      │  │
│  └───────────────────────────────────────────────────────┘  │
│  Database: Project.environment_status = 'hibernated'        │
│  Database: ProjectSnapshot record with status = 'ready'     │
└─────────────────────────────────────────────────────────────┘
                         │
                         │ User returns
                         ▼
            ┌─────────────────────────────┐
            │ RESTORATION (Snapshot)      │
            │                             │
            │ 1. Create PVC with dataSource│
            │    pointing to VolumeSnapshot│
            │ 2. Create namespace + pods  │
            │ 3. EBS lazy-loads on access │
            │                             │
            │ (< 10 seconds total!)       │
            └─────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  ACTIVE STATE                               │
│  (Cycle continues... deps auto-installed if missing!)        │
└─────────────────────────────────────────────────────────────┘
```

**Key Implementation Details**:

```python
# PVC Discovery (_get_hibernation_pvc_names)
# Lists all PVCs in namespace, returns project-storage + any service PVCs
# (labeled tesslate.io/component=service-storage or prefixed svc-)

# Hibernation (_save_to_snapshot, via SnapshotManager)
1. Backend: Discover all PVCs via _get_hibernation_pvc_names(namespace)
2. Backend: Skip snapshot ONLY if project is NOT initialized AND there are no service PVCs
   (previously skipped whenever project was not initialized)
3. Backend: For each PVC, create VolumeSnapshot and wait for readyToUse (timeout: 300s)
4. Backend: Delete namespace (cascades to all PVCs, pods, services, ingresses)
5. Database: Create ProjectSnapshot record per PVC, update project status

# Restoration (_restore_from_snapshot, via SnapshotManager)
1. Backend: Restore project-storage PVC first (if snapshot exists)
2. Backend: Query get_latest_ready_snapshots_by_pvc() for service PVC snapshots
3. Backend: Iterate and restore each service PVC from its snapshot
4. EBS provisioner creates new volumes from snapshots (lazy-load)
5. Backend: Create namespace, file-manager pod mounts restored PVCs
6. Database: Update project status to 'active'
```

**Why VolumeSnapshots are superior**:
- ✅ Near-instant restore (< 10s vs 30-90s with S3 ZIP)
- ✅ Fast restore (EBS lazy-loads data on access)
- ✅ Non-blocking creation (returns immediately)
- ✅ Timeline UI - up to 5 manual snapshots per project
- ✅ 30-day soft delete retention for recovery

### 6. Pod Affinity (Multi-Container Projects)

For projects with multiple containers (frontend + backend), **all pods must run on the same node**:

**Reason**: PersistentVolumeClaim (PVC) uses `ReadWriteOnce` (RWO) access mode, which can only be mounted by pods on the same node.

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

This ensures all pods with the same `project-id` label run on the same node, allowing them to share the RWO volume.

**Alternative**: Use `ReadWriteMany` (RWX) storage class, but this is more expensive and not available on all cloud providers.

## Project Lifecycle

### Opening a Project (Ensure Environment)

```python
namespace = await orchestrator.ensure_project_environment(
    project_id=project_id,
    user_id=user_id,
    is_hibernated=False
)
```

**Steps**:
1. **Create namespace**: `proj-{uuid}` with labels
2. **Create NetworkPolicy**: Isolate project from other namespaces
3. **Create PVC**: `project-storage` (5Gi RWO)
4. **Copy TLS secret**: For HTTPS ingress (wildcard cert)
5. **Create file-manager deployment**: Always-running pod
6. **Wait for ready**: File-manager must be ready before returning
7. **Restore from S3** (if hibernated): Download, unzip, validate

**Database update**: `Project.environment_status = 'active'`

### Adding Container to Graph (Initialize Files)

```python
success = await orchestrator.initialize_container_files(
    project_id=project_id,
    user_id=user_id,
    container_id=container_id,
    container_directory="frontend",
    git_url="https://github.com/tesslate/next-js-15.git",
    git_branch="main"
)
```

**Steps**:
1. Get file-manager pod name
2. Check if directory exists and has files
3. If empty or missing, run `git clone` via `kubectl exec`
4. Git clone script:
   - Clones to temp directory
   - Removes `.git` folder (save space)
   - Copies to `/app/{container_directory}/`
   - Changes ownership to `node:node` (1000:1000)
   - Does NOT install dependencies (happens during container startup)

**Important**: Files are populated BEFORE the dev container starts. No init containers needed!

### Starting a Container

```python
result = await orchestrator.start_container(
    project=project,
    container=container,
    all_containers=all_containers,
    connections=connections,
    user_id=user_id,
    db=db
)
```

**Steps**:
1. **Ensure environment exists** (creates namespace if needed)
2. **Read TESSLATE.md** from file-manager pod:
   ```python
   base_config = await self._get_tesslate_config_from_pod(namespace, container_directory)
   port = base_config.port  # e.g., 3000
   startup_command = base_config.start_command  # e.g., "npm run dev"
   ```
3. **Create Deployment**:
   - Image: `tesslate-devserver:latest`
   - Volume: Mount existing PVC at `/app`
   - Working dir: `/app/{container_directory}`
   - Command: `tmux new-session -d -s main '{startup_command}' && exec tail -f /dev/null`
   - Probes: Startup, readiness, liveness (HTTP on port)
   - Pod affinity: If multi-container project

**Startup Command Priority Chain**:
1. **DB startup_command** (`Container.startup_command`): Set by setup-config or project creation
2. **`.tesslate/config.json`**: Read from PVC via file-manager pod (fallback for older projects)
3. **TESSLATE.md**: Legacy config file parsed for port and start_command
4. **Generic fallback**: `npm install && npm run dev`
4. **Create Service**: ClusterIP, selector by `container-id`
5. **Create Ingress**: NGINX, TLS with wildcard cert
6. **Return URL**: `https://{slug}-{container}.your-domain.com`

**Important**: No init containers! Files already exist on PVC from `initialize_container_files()`.

### Stopping a Container

```python
await orchestrator.stop_container(
    project_slug=project_slug,
    project_id=project_id,
    container_name=container_name,
    user_id=user_id
)
```

**Steps**:
1. Delete Deployment: `dev-{container_directory}`
2. Delete Service: `dev-{container_directory}`
3. Delete Ingress: `dev-{container_directory}`

**Important**: Files persist on PVC! File-manager pod still running. Only the dev server is stopped.

### Leaving Project (Hibernate)

```python
success = await orchestrator.hibernate_project(project_id, user_id, db=db)
```

**Steps**:
1. **Discover PVCs** via `_get_hibernation_pvc_names(namespace)`:
   - Always includes `project-storage`
   - Includes service PVCs labeled `tesslate.io/component=service-storage` or prefixed `svc-`
2. **Skip check**: Only skips snapshot if the project is NOT initialized AND there are no service PVCs. If there are service PVCs (e.g., Postgres data), snapshots are created even for uninitialized projects.
3. **Create VolumeSnapshots per PVC** (via `SnapshotManager`):
   - For each PVC discovered in step 1, create a VolumeSnapshot and wait for `status.readyToUse: true` (timeout: 300s)
   - Create a ProjectSnapshot database record per PVC (with `pvc_name` field)
   - Snapshot rotation (`_rotate_snapshots`) is scoped per PVC
   - If any snapshot fails, hibernation is aborted
4. **Delete namespace**: Cascades to all resources (PVCs, pods, services, ingresses)
5. **Update database**: `Project.environment_status = 'hibernated'`, `hibernated_at = now()`

**Safety**: If any snapshot creation fails, namespace is NOT deleted (preserves data). Error is raised to user.

### Returning to Hibernated Project (Restore)

```python
namespace = await orchestrator.restore_project(project_id, user_id)
```

**Steps**:
1. **Create namespace**
2. **Restore project-storage PVC** (via `SnapshotManager`):
   - Check for existing `project-storage` hibernation snapshot
   - Create PVC with `dataSource` pointing to VolumeSnapshot
   - EBS provisioner creates new volume from snapshot (lazy-load)
3. **Restore service PVCs** (via `SnapshotManager`):
   - Query `get_latest_ready_snapshots_by_pvc()` for all service PVC snapshots
   - Iterate and restore each service PVC from its corresponding snapshot
   - If any service PVC restore fails, returns partial success (project-storage may still be restored)
4. **Create file-manager pod** (mounts restored PVCs)
5. **Update database**: `Project.environment_status = 'active'`, `hibernated_at = NULL`

**Key benefit**: node_modules, all dependencies, and service data (databases, caches) are preserved in per-PVC snapshots. No npm install needed - the project is ready in seconds!

### Deleting Project (Permanent)

```python
await orchestrator.delete_project_namespace(project_id, user_id)
```

**Steps**:
1. Check if namespace exists
2. Delete namespace (cascades all resources)
3. **Soft-delete snapshots**: Marks ProjectSnapshot records for 30-day retention
4. Daily cleanup CronJob deletes expired snapshots after 30 days

## File Operations

All file operations go through the file-manager pod (or dev container if running):

### Reading a File

```python
content = await orchestrator.read_file(
    user_id=user_id,
    project_id=project_id,
    container_name="frontend",
    file_path="src/App.tsx",
    subdir="frontend"
)
```

**Implementation**:
```python
pod_name = await k8s_client.get_file_manager_pod(namespace)
full_path = f"/app/{subdir}/{file_path}"
result = await k8s_client._exec_in_pod(
    pod_name, namespace, "file-manager",
    ["cat", full_path],
    timeout=30
)
return result
```

### Writing a File

```python
success = await orchestrator.write_file(
    user_id=user_id,
    project_id=project_id,
    container_name="frontend",
    file_path="src/NewComponent.tsx",
    content=code,
    subdir="frontend"
)
```

**Implementation**:
```python
# Use base64 to handle special characters
encoded = base64.b64encode(content.encode()).decode()

# Ensure directory exists
await k8s_client._exec_in_pod(..., ["mkdir", "-p", dir_path], ...)

# Write file
await k8s_client._exec_in_pod(
    ...,
    ["sh", "-c", f"echo '{encoded}' | base64 -d > {full_path}"],
    ...
)
```

## Shell Execution

Execute commands in the file-manager pod (or dev container):

```python
output = await orchestrator.execute_command(
    user_id=user_id,
    project_id=project_id,
    container_name="frontend",
    command=["npm", "install", "axios"],
    timeout=300,
    working_dir="frontend"
)
```

**Implementation**:
```python
pod_name = await k8s_client.get_file_manager_pod(namespace)
full_command = ["sh", "-c", f"cd /app/{working_dir} && {' '.join(command)}"]
output = await k8s_client._exec_in_pod(pod_name, namespace, "file-manager", full_command, timeout)
```

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

**URL Pattern**: `https://{project-slug}-{container-directory}.{domain}`

**TLS**: Uses wildcard certificate (`*.your-domain.com`) copied to project namespace.

### NetworkPolicy (Isolation)

Each project namespace gets a NetworkPolicy:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: project-isolation
  namespace: proj-d4f6e8a2-...
spec:
  podSelector: {}  # Apply to all pods
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Allow from NGINX ingress
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress-nginx
    # Allow from Tesslate backend (for file operations)
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: tesslate
    # Allow within namespace (inter-container)
    - from:
        - podSelector: {}
  egress:
    # Allow DNS
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: UDP
          port: 53
    # Allow HTTPS (npm, git, APIs)
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
      ports:
        - protocol: TCP
          port: 443
        - protocol: TCP
          port: 80
```

**Effect**:
- ✅ Ingress from NGINX (public access to dev servers)
- ✅ Ingress from Tesslate backend (file operations)
- ✅ Ingress within namespace (frontend → backend)
- ✅ Egress to DNS, HTTPS (npm install, git clone, external APIs)
- ❌ Ingress from other projects
- ❌ Egress to internal cluster services (unless explicitly allowed)

## Activity Tracking & Cleanup

### Database-Based Tracking

Unlike Docker mode (in-memory), Kubernetes mode uses the database:

```python
# Track activity (in routers)
from orchestrator.app.services.activity_tracker import track_project_activity
await track_project_activity(db, project_id, user_id)

# Updates: Project.last_activity = now()
```

**Why database?**
- ✅ Survives orchestrator backend restarts
- ✅ Supports horizontal scaling (multiple backend replicas)
- ✅ Consistent with hibernated projects

### Cleanup Cronjobs

Two Kubernetes CronJobs manage hibernation and snapshot cleanup:

**1. Hibernation CronJob** (`cleanup-cronjob.yaml`):
```yaml
schedule: "*/2 * * * *"  # Every 2 minutes
command: ["python", "-c", "
  from orchestrator.app.services.orchestration import get_orchestrator;
  import asyncio;
  orchestrator = get_orchestrator();
  asyncio.run(orchestrator.cleanup_idle_environments(30))
"]
```

**2. Snapshot Cleanup CronJob** (`snapshot-cleanup-cronjob.yaml`):
```yaml
schedule: "0 3 * * *"  # Daily at 3 AM UTC
command: ["python", "-c", "
  from orchestrator.app.services.snapshot_manager import get_snapshot_manager;
  import asyncio;
  snapshot_manager = get_snapshot_manager();
  asyncio.run(snapshot_manager.cleanup_expired_snapshots())
"]
```

**Hibernation logic**:
```python
async def cleanup_idle_environments(self, idle_timeout_minutes=30):
    cutoff_time = now() - timedelta(minutes=idle_timeout_minutes)

    # Find projects where last_activity < cutoff_time and environment_status='active'
    idle_projects = await db.query(Project).filter(
        Project.environment_status == 'active',
        or_(Project.last_activity < cutoff_time, Project.last_activity.is_(None))
    ).all()

    for project in idle_projects:
        # Hibernate project (create VolumeSnapshot + delete namespace)
        await self.hibernate_project(project.id, project.owner_id, db=db)

        # Update status
        project.environment_status = 'hibernated'
        project.hibernated_at = now()
        await db.commit()
```

**WebSocket Notification**: When hibernating, the backend sends a WebSocket message to the user:
```json
{
  "environment_status": "hibernating",
  "message": "Saving project files...",
  "action": "redirect_to_projects"
}
```

This redirects the user to the projects list if they're still viewing the hibernated project.

## Configuration

Key environment variables (see `orchestrator/app/config.py`):

```bash
# Deployment mode
DEPLOYMENT_MODE=kubernetes

# Image configuration
K8S_DEVSERVER_IMAGE=tesslate-devserver:latest
K8S_IMAGE_PULL_POLICY=IfNotPresent
K8S_IMAGE_PULL_SECRET=  # Empty for local images, set for private registry

# Storage
K8S_STORAGE_CLASS=tesslate-block-storage
K8S_PVC_SIZE=10Gi
K8S_PVC_ACCESS_MODE=ReadWriteOnce

# Snapshots
K8S_SNAPSHOT_CLASS=tesslate-ebs-snapshots
K8S_SNAPSHOT_RETENTION_DAYS=30
K8S_MAX_SNAPSHOTS_PER_PROJECT=5
K8S_SNAPSHOT_READY_TIMEOUT_SECONDS=300

# Namespace configuration
K8S_NAMESPACE_PER_PROJECT=true
K8S_ENABLE_POD_AFFINITY=true  # Required for RWO PVCs
K8S_AFFINITY_TOPOLOGY_KEY=kubernetes.io/hostname

# Network policies
K8S_ENABLE_NETWORK_POLICIES=true

# TLS
K8S_WILDCARD_TLS_SECRET=tesslate-wildcard-tls

# Hibernation
K8S_HIBERNATION_IDLE_MINUTES=30
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
kubectl exec -n $NAMESPACE deployment/file-manager -c file-manager -- cat /app/frontend/package.json
```

### Check Ingress

```bash
kubectl get ingress -n $NAMESPACE
kubectl describe ingress dev-frontend -n $NAMESPACE
```

### Check PVC

```bash
kubectl get pvc -n $NAMESPACE
kubectl describe pvc project-storage -n $NAMESPACE
```

### Check NetworkPolicy

```bash
kubectl get networkpolicy -n $NAMESPACE
kubectl describe networkpolicy project-isolation -n $NAMESPACE
```

## Common Issues

### ImagePullBackOff

**Problem**: Pod stuck in `ImagePullBackOff`

**Cause**: Image not loaded into cluster

**Solutions**:
- **Minikube**: `minikube -p tesslate image load tesslate-devserver:latest`
- **EKS**: Check ECR credentials, ensure image is pushed

### Volume Mount Errors

**Problem**: `volumeMounts[0].name: Not found`

**Cause**: Volume name mismatch in manifest

**Solution**: Ensure volume names are consistent in `helpers.py`:
```python
# Volume definition
volumes = [client.V1Volume(name="project-storage", ...)]

# Volume mount
volume_mounts = [client.V1VolumeMount(name="project-storage", ...)]
```

### 503 Service Unavailable

**Problem**: Ingress returns 503

**Causes**:
1. Pod not ready (check startup probe)
2. Service selector doesn't match pod labels
3. NGINX ingress controller not finding endpoints

**Debug**:
```bash
# Check pod readiness
kubectl get pods -n $NAMESPACE

# Check service endpoints
kubectl get endpoints -n $NAMESPACE

# Check ingress controller logs
kubectl logs -n ingress-nginx deployment/ingress-nginx-controller
```

### Snapshot Hibernation Failures

**Problem**: Hibernation fails with "snapshot not ready" or "snapshot creation failed"

**Debug**:
```bash
# Check backend pod logs
kubectl logs -n tesslate deployment/tesslate-backend

# Check VolumeSnapshot status
kubectl get volumesnapshot -n proj-<uuid>
kubectl describe volumesnapshot <name> -n proj-<uuid>

# Check snapshot controller logs
kubectl logs -n kube-system -l app=snapshot-controller
```

**Common causes**:
- VolumeSnapshotClass not configured (`tesslate-ebs-snapshots`)
- EBS CSI driver not installed or misconfigured
- File-manager pod not found (project environment not created)
- PVC doesn't exist or is not bound

### Pod Affinity Violations

**Problem**: Pods stuck in `Pending` with "failed affinity constraint"

**Cause**: No single node can fit all pods for a multi-container project

**Solutions**:
- Increase node capacity
- Reduce pod resource requests
- Use ReadWriteMany (RWX) storage (if available)

## Advantages & Limitations

### Advantages

✅ **Scalable**: Thousands of projects, horizontal scaling of backend
✅ **Cost-efficient**: Hibernation via EBS snapshots saves compute resources
✅ **Isolated**: Namespace + NetworkPolicy = strong multi-tenancy
✅ **Fast restore**: Near-instant (< 10s) via EBS lazy-loading
✅ **Resilient**: Database-based tracking, survives backend restarts
✅ **Timeline UI**: Up to 5 snapshots per project for version history
✅ **Recovery**: 30-day soft delete retention for accidental deletions

### Limitations

❌ **Complex**: More moving parts than Docker mode
❌ **Pod scheduling**: Container startup depends on K8s scheduler
❌ **RWO constraint**: Multi-container projects need pod affinity (same node)
❌ **Single AZ**: EBS snapshots don't replicate across availability zones

## Next Steps

- See [kubernetes-client.md](./kubernetes-client.md) for K8s API wrapper details
- See [kubernetes-helpers.md](./kubernetes-helpers.md) for manifest generation
- Compare with [docker-mode.md](./docker-mode.md) for local development
