# Deployment Modes Documentation

This document explains OpenSail's two deployment modes: **Docker mode** (local development) and **Kubernetes mode** (production). Each mode has different routing, storage, and configuration requirements.

**Visual Reference**: For deployment pipeline diagrams, see `diagrams/deployment-pipeline.mmd` (when created).

## Overview

OpenSail supports two deployment modes configured via the `DEPLOYMENT_MODE` environment variable:

| Mode | Use Case | Routing | Storage | Complexity |
|------|----------|---------|---------|------------|
| **Docker** | Local development | Traefik (*.localhost) | Local filesystem | Low |
| **Kubernetes** | Production (cloud) | NGINX Ingress | Volume Hub + btrfs CSI + S3 CAS | High |

**Key Setting** (from `config.py`):
```python
deployment_mode: str = "docker"  # or "kubernetes"

@property
def is_docker_mode(self) -> bool:
    return self.deployment_mode.lower() == "docker"

@property
def is_kubernetes_mode(self) -> bool:
    return self.deployment_mode.lower() == "kubernetes"
```

## Docker Mode (Local Development)

### Overview

Docker mode uses Docker Desktop with Traefik for local development. User projects are stored directly on the local filesystem with simple volume mounts.

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Docker Desktop                        │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────┐        ┌──────────────┐             │
│  │   Frontend   │        │  Orchestrator│             │
│  │  (Container) │        │  (Container) │             │
│  └──────────────┘        └──────────────┘             │
│                                                         │
│  ┌──────────────┐        ┌──────────────┐             │
│  │  PostgreSQL  │        │    Traefik   │             │
│  │  (Container) │        │ (Reverse Proxy)│            │
│  └──────────────┘        └──────────────┘             │
│                                                         │
│  ┌─────────────────────────────────────┐               │
│  │  User Project Containers (Legacy)   │               │
│  │  NOTE: Multi-container orchestration│               │
│  │  was removed. Docker mode now uses  │               │
│  │  direct filesystem access for files │               │
│  └─────────────────────────────────────┘               │
│                                                         │
└─────────────────────────────────────────────────────────┘
                         │
                         ↓
                ┌─────────────────┐
                │  Local Filesystem│
                │  users/          │
                │    {user_id}/    │
                │      {project}/  │
                └─────────────────┘
```

### Routing (Traefik)

**Pattern**: `*.localhost` subdomains routed to containers

**Examples**:
- Frontend: `http://localhost:3000` or `http://studio.localhost`
- Backend: `http://localhost:8000` or `http://api.localhost`
- User project (legacy): `http://{project-slug}.localhost`

**Traefik Configuration**:
- Automatic service discovery (Docker labels)
- HTTP routing (no SSL for localhost)
- Wildcard subdomain support

**Note**: Container routing via Traefik was removed. User projects access files directly from filesystem in Docker mode.

### Storage (Local Filesystem)

**Pattern**: Direct volume mounts to `users/` directory

**Directory Structure**:
```
orchestrator/
  users/
    {user_id}/
      {project_slug}/
        frontend/
          src/
          package.json
          vite.config.ts
        backend/
          main.py
          requirements.txt
        tesslate.json
```

**File Operations**:
- **Read**: `open(f"users/{user_id}/{project_slug}/{path}").read()`
- **Write**: `open(f"users/{user_id}/{project_slug}/{path}", 'w').write(content)`
- **No S3**: Files persist locally (no hydration/dehydration)

**Advantages**:
- ✅ Fast I/O (no network calls)
- ✅ Simple debugging (files visible in IDE)
- ✅ No S3 costs

**Disadvantages**:
- ❌ Not production-ready (single machine)
- ❌ No horizontal scaling
- ❌ Data loss on container restart (without volumes)

### Configuration

**Required Environment Variables**:
```bash
# Deployment mode
DEPLOYMENT_MODE=docker

# Base URL for dev containers (legacy - not used)
DEV_SERVER_BASE_URL=http://localhost

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/tesslate

# Auth
SECRET_KEY=your-secret-key-here
```

**Optional Settings**:
```bash
# CORS (for frontend at localhost:3000)
CORS_ORIGINS=http://localhost:3000,http://studio.localhost
APP_DOMAIN=localhost

# OAuth (for GitHub/Google login)
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

### Docker Compose Setup

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/docker-compose.yml`

**Key Services**:
```yaml
services:
  # Frontend (React + Vite)
  frontend:
    build:
      context: ./app
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    environment:
      - VITE_API_BASE_URL=http://localhost:8000

  # Backend (FastAPI)
  orchestrator:
    build:
      context: ./orchestrator
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - DEPLOYMENT_MODE=docker
      - DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/tesslate
    volumes:
      - ./orchestrator/users:/app/users  # Project files

  # Database (PostgreSQL)
  postgres:
    image: postgres:14
    ports:
      - "5432:5432"
    environment:
      - POSTGRES_DB=tesslate
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

### Limitations

**Docker Mode Does NOT Support**:
- ❌ Multi-container user projects (removed - legacy system)
- ❌ Container isolation via NetworkPolicy (only K8s)
- ❌ Volume Hub / btrfs storage (no hibernation/restore)
- ❌ Horizontal scaling (single orchestrator instance)
- ❌ Automatic SSL certificates (localhost only)

**What Docker Mode IS For**:
- ✅ Local development and testing
- ✅ Fast iteration on orchestrator code
- ✅ Simple debugging (files on disk)
- ✅ No cloud dependencies (works offline)

## Kubernetes Mode (Production)

### Overview

Kubernetes mode runs in a K8s cluster with NGINX Ingress for routing and a 3-layer storage architecture (Volume Hub, btrfs CSI nodes, S3 CAS persistence) for project storage. Each user project gets a dedicated namespace with strict isolation.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Kubernetes Cluster                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Namespace: tesslate                                        │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  Frontend  │  │ Orchestrator │  │  PostgreSQL  │       │
│  │    Pod     │  │     Pod      │  │     Pod      │       │
│  └────────────┘  └──────────────┘  └──────────────┘       │
│                                                             │
│  Namespace: proj-{uuid-1}                                   │
│  ┌────────────────────────────────────────────────┐        │
│  │  File Manager Pod (Always Running)             │        │
│  │  - Handles file operations                     │        │
│  │  - Git clone/commit/push                       │        │
│  └────────────────────────────────────────────────┘        │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐           │
│  │  Frontend  │  │  Backend   │  │  Database  │           │
│  │    Pod     │  │    Pod     │  │    Pod     │           │
│  └────────────┘  └────────────┘  └────────────┘           │
│  ┌────────────────────────────────────────────────┐        │
│  │  CSI PV+PVC (btrfs subvolume on compute node) │        │
│  │  - Shared by all pods in namespace             │        │
│  │  - Volume Hub manages lifecycle + node cache   │        │
│  │  - Sync daemon pushes changes to S3 CAS        │        │
│  └────────────────────────────────────────────────┘        │
│  ┌────────────────────────────────────────────────┐        │
│  │  NetworkPolicy (Zero cross-project traffic)    │        │
│  └────────────────────────────────────────────────┘        │
│                                                             │
│  Namespace: proj-{uuid-2}                                   │
│  ┌────────────────────────────────────────────────┐        │
│  │  File Manager Pod + Dev Pods + PVC             │        │
│  └────────────────────────────────────────────────┘        │
│                                                             │
│  Namespace: ingress-nginx                                   │
│  ┌────────────────────────────────────────────────┐        │
│  │  NGINX Ingress Controller                      │        │
│  │  - Routes *.your-domain.com to namespaces         │        │
│  │  - SSL termination (wildcard cert)             │        │
│  └────────────────────────────────────────────────┘        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                         │
                         ↓
     ┌───────────────────────────────────────────────┐
     │          3-Layer Storage Architecture          │
     ├───────────────────────────────────────────────┤
     │  Volume Hub (kube-system, gRPC :9750)         │
     │  - Storageless orchestrator                   │
     │  - Volume lifecycle: create, delete, cache    │
     │  - Node placement + peer transfer             │
     │  - Triggers S3 sync on owning node            │
     ├───────────────────────────────────────────────┤
     │  btrfs CSI Nodes (compute nodes)              │
     │  - Local NVMe/SSD btrfs volumes               │
     │  - CoW snapshot-clone from templates           │
     │  - FileOps gRPC :9742 (local I/O, ~0.01ms)   │
     │  - Sync daemon pushes to S3 CAS               │
     ├───────────────────────────────────────────────┤
     │  S3 CAS (Content-Addressable Store)           │
     │  - Incremental, deduplicated layer store      │
     │  - Durable persistence across node failures   │
     │  - Restore = pull CAS layers → btrfs subvol   │
     └───────────────────────────────────────────────┘
```

### Routing (NGINX Ingress)

**Pattern**: Subdomains routed to K8s Services via Ingress

**Examples**:
- Frontend: `https://your-domain.com`
- Backend: `https://api.your-domain.com`
- User project (frontend): `https://{project_slug}-frontend.your-domain.com`
- User project (backend): `https://{project_slug}-backend.your-domain.com`

**Ingress Configuration** (from `kubernetes/helpers.py`):
```python
def create_ingress_manifest(
    namespace: str,
    project_id: UUID,
    container_id: UUID,
    container_directory: str,
    project_slug: str,
    port: int,
    domain: str,
    ingress_class: str = "nginx",
    tls_secret: str = None,
) -> client.V1Ingress:
    # Host pattern: {project_slug}-{container_directory}.{domain}
    host = f"{project_slug}-{container_directory}.{domain}"

    # Annotations: WebSocket support for HMR (no cert-manager / ssl-redirect)
    annotations = {
        "nginx.ingress.kubernetes.io/proxy-http-version": "1.1",
        "nginx.ingress.kubernetes.io/proxy-read-timeout": "3600",
        "nginx.ingress.kubernetes.io/proxy-send-timeout": "3600",
    }

    # TLS added only if tls_secret is provided (production)
    # ...
```

**SSL Certificates**:
- Wildcard cert: `*.your-domain.com` (covers all user projects)
- Provisioned via cert-manager + Let's Encrypt
- DNS-01 challenge (Cloudflare API)
- Automatic renewal

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/base/ingress/certificate.yaml`

### Storage (Volume Hub + btrfs CSI + S3 CAS)

**Concept**: 3-layer storage architecture where a storageless Volume Hub orchestrates btrfs subvolumes on compute nodes, with S3 CAS (Content-Addressable Store) for durable persistence.

**Architecture Layers**:

| Layer | Component | Role |
|-------|-----------|------|
| **Control Plane** | Volume Hub (`kube-system`, gRPC `:9750`) | Storageless orchestrator: volume lifecycle, node selection, cache placement, S3 sync triggers |
| **Data Plane** | btrfs CSI nodes (compute nodes) | Local NVMe/SSD btrfs filesystems, CoW snapshot-clone from templates, FileOps gRPC `:9742` |
| **Persistence** | S3 CAS (Content-Addressable Store) | Incremental, deduplicated layer store for durable cross-node persistence |

**Orchestrator Integration**: The orchestrator talks to the Hub via a thin `VolumeManager` client (`volume_manager.py` / `hub_client.py`). It never touches btrfs or S3 directly.

**Lifecycle**:
```
┌─────────────────────────────────────────────────────────┐
│  1. PROJECT CREATION                                    │
│                                                         │
│  VolumeManager.create_volume(template="nextjs")         │
│    ↓                                                    │
│  Hub picks the best available compute node              │
│    ↓                                                    │
│  Node creates btrfs subvolume via CoW clone of template │
│    - Instant: no file copies, shared extents            │
│    - node_modules, lock files already installed          │
│    ↓                                                    │
│  Hub returns (volume_id, node_name)                     │
│    - Stored on Project.volume_id / Project.cache_node   │
│                                                         │
│  ✅ Volume ready — zero npm install on first boot       │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  2. PROJECT OPEN (Start Environment)                    │
│                                                         │
│  ComputeManager.start_environment() calls:              │
│    VolumeManager.ensure_cached(volume_id, candidates)   │
│    ↓                                                    │
│  Hub validates candidates against live node set         │
│    - Fast path: already cached on a live node → return  │
│    - Slow path: peer-transfer or restore from S3 CAS   │
│    ↓                                                    │
│  Create namespace proj-{uuid}                           │
│    ↓                                                    │
│  Create CSI PV+PVC pointing to btrfs subvolume on node  │
│    - driver: btrfs.csi.tesslate.io                     │
│    - volumeHandle: {volume_id}                          │
│    - nodeAffinity: locked to the cache_node             │
│    ↓                                                    │
│  Deploy dev containers + service containers             │
│    - All pods mount the same CSI PVC (pod affinity)     │
│                                                         │
│  ✅ Project running with local btrfs I/O                │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  3. RUNTIME (Fast Local I/O + Background Sync)          │
│                                                         │
│  User edits files via:                                  │
│    - Monaco editor (write_file tool)                    │
│    - Agent commands (bash, git)                         │
│    - Manual uploads                                     │
│    ↓                                                    │
│  FileOps gRPC (port 9742) on the compute node           │
│    - Direct btrfs I/O, ~0.01ms latency                 │
│    - All containers share same CSI PVC (pod affinity)   │
│    ↓                                                    │
│  Sync daemon on the node pushes changes to S3 CAS       │
│    - Incremental: only changed blocks/layers            │
│    - Content-addressed: automatic deduplication          │
│    - Non-blocking: runs in background on the node       │
│                                                         │
│  User can manually create snapshots (Timeline UI)       │
│    - Up to 5 K8s VolumeSnapshots per project            │
│    - SnapshotManager creates btrfs-backed snapshots     │
│    - Non-blocking: returns immediately, polls for ready │
│                                                         │
│  ✅ Fast local I/O + durable S3 persistence             │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  4. PROJECT STOP / HIBERNATION                          │
│                                                         │
│  User leaves project OR project idles for 10+ min       │
│    ↓                                                    │
│  hibernate_project_bg() orchestrates the full flow:      │
│    - ComputeManager.stop_environment():                  │
│      - Delete namespace (cascades pods, services, PVC)  │
│      - Delete cluster-scoped PVs (Retain policy keeps   │
│        btrfs subvolumes intact on the node)             │
│    - VolumeManager.trigger_sync(volume_id) — final S3   │
│      push to ensure all data is persisted (separate     │
│      step in hibernate.py, NOT in stop_environment)     │
│                                                         │
│  Data remains in two places:                            │
│    1. btrfs subvolume on the node (fast local cache)    │
│    2. S3 CAS layers (durable, cross-node)              │
│                                                         │
│  ✅ Cluster resources freed, data persisted             │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  5. PROJECT DELETION (Soft Delete)                      │
│                                                         │
│  User deletes project                                   │
│    ↓                                                    │
│  VolumeManager.delete_volume(volume_id)                 │
│    - Hub deletes from S3 + all node caches              │
│    - Idempotent                                         │
│    ↓                                                    │
│  SnapshotManager marks K8s snapshots as soft-deleted    │
│    - Set soft_delete_expires_at to 30 days from now     │
│    - VolumeSnapshots NOT deleted immediately            │
│    ↓                                                    │
│  Daily cleanup CronJob:                                 │
│    - Delete expired K8s VolumeSnapshot resources        │
│    - Update database record status to "deleted"         │
│                                                         │
│  ✅ 30-day recovery window for accidental deletions     │
└─────────────────────────────────────────────────────────┘
```

**Volume Hub API** (from `VolumeManager` / `HubClient`):
```python
# orchestrator/app/services/volume_manager.py (thin client)
# orchestrator/app/services/hub_client.py (gRPC transport)

vm = get_volume_manager()

# Create a volume (CoW clone from template on best node)
volume_id, node_name = await vm.create_volume(template="nextjs")

# Ensure volume is cached on a live, schedulable node
node_name = await vm.ensure_cached(volume_id, candidate_nodes=["node-1", "node-2"])

# Trigger S3 sync on the owning node (non-blocking)
await vm.trigger_sync(volume_id)

# Create service-specific subvolume (e.g. postgres data dir)
svc_vol_id = await vm.create_service_volume(volume_id, "postgres")

# Delete volume from Hub + S3 + all node caches
await vm.delete_volume(volume_id)
```

**CSI PV+PVC** (created by `ComputeManager.start_environment()`):
```yaml
# PV — cluster-scoped, locked to a specific node
apiVersion: v1
kind: PersistentVolume
metadata:
  name: pv-{volume_id}
spec:
  capacity:
    storage: 5Gi
  accessModes: [ReadWriteOnce]
  persistentVolumeReclaimPolicy: Retain   # btrfs subvolumes survive PV deletion
  csi:
    driver: btrfs.csi.tesslate.io
    volumeHandle: "{volume_id}"
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values: ["{node_name}"]
---
# PVC — namespaced, binds to the PV above
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: project-source
  namespace: proj-{project_id}
spec:
  storageClassName: ""       # Pre-bound to specific PV
  volumeName: pv-{volume_id}
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 10Gi           # Function default; config.k8s_pvc_size overrides (default "5Gi")
```

**SnapshotManager** (K8s VolumeSnapshot API — Timeline UI):

SnapshotManager (`snapshot_manager.py`) still manages K8s VolumeSnapshots for the Timeline UI, but snapshots now use btrfs under the hood (via the btrfs CSI driver's VolumeSnapshotClass) instead of EBS. The same create/restore/rotate/soft-delete logic applies:
- Up to 5 snapshots per project (configurable via `K8S_MAX_SNAPSHOTS_PER_PROJECT`)
- Hibernation snapshots created automatically on stop
- Manual snapshots created via Timeline UI
- 30-day soft-delete retention for recovery
- VolumeSnapshotClass: `tesslate-ebs-snapshots` (name retained for compatibility; backed by btrfs CSI)

**Advantages**:
- Instant project creation via btrfs CoW template cloning (no npm install)
- Fast local I/O (~0.01ms via FileOps gRPC on compute node)
- Durable persistence via S3 CAS (survives node failures)
- Incremental, deduplicated storage (CAS only stores changed blocks)
- Hub handles node failures transparently (peer-transfer or S3 restore)
- Service subvolumes for stateful containers (e.g. postgres data dir)
- Timeline UI with up to 5 btrfs-backed VolumeSnapshots
- 30-day soft-delete retention for recovery

**Key Files**:
- `orchestrator/app/services/volume_manager.py` — Thin VolumeManager client
- `orchestrator/app/services/hub_client.py` — gRPC client for Volume Hub
- `orchestrator/app/services/compute_manager.py` — Start/stop environment, creates CSI PV+PVC
- `orchestrator/app/services/snapshot_manager.py` — K8s VolumeSnapshot API (Timeline UI)

### Namespace Isolation

**Pattern**: One namespace per project (`proj-{project_id}`)

**Resources per Namespace**:
```yaml
# Namespace
apiVersion: v1
kind: Namespace
metadata:
  name: proj-550e8400-e29b-41d4-a716-446655440000
  labels:
    tesslate.io/project-id: "550e8400-e29b-41d4-a716-446655440000"
    tesslate.io/user-id: "123e4567-e89b-12d3-a456-426614174000"

---
# CSI PV+PVC (btrfs subvolume on compute node)
# Created by ComputeManager.start_environment() — see Storage section above.
# PV is cluster-scoped with nodeAffinity; PVC is namespace-scoped and pre-bound.
# All pods in the namespace share this PVC via pod affinity.

---
# Dev Container Deployment (example: frontend)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend
spec:
  replicas: 1
  template:
    spec:
      affinity:  # Pod affinity keeps all containers on the same node as the CSI volume
        podAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchLabels:
                tesslate.io/project-id: "550e8400-e29b-41d4-a716-446655440000"
            topologyKey: kubernetes.io/hostname
      containers:
      - name: dev-server
        image: tesslate-devserver:latest
        command: ["npm", "run", "dev"]
        volumeMounts:
        - name: project-source
          mountPath: /app
      volumes:
      - name: project-source
        persistentVolumeClaim:
          claimName: project-source

---
# NetworkPolicy (Zero cross-project traffic)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: project-isolation
spec:
  podSelector: {}  # All pods in namespace
  policyTypes: [Ingress, Egress]
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: ingress-nginx  # Only NGINX can reach pods
  egress:
  - to: []  # Internet + cluster DNS
```

**Benefits**:
- ✅ Strong isolation (can't access other projects)
- ✅ Easy cleanup (delete namespace → everything deleted)
- ✅ RBAC per project (fine-grained permissions)
- ✅ Resource quotas (CPU/memory limits)

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/kubernetes_orchestrator.py`

### Pod Affinity (Multi-Container Projects)

**Problem**: CSI PVs with node affinity pin the btrfs subvolume to a specific compute node. All pods must run on that node to access the volume.

**Solution**: Pod affinity ensures all containers in a project run on the same node as the CSI volume.

**Configuration** (from `config.py`):
```python
k8s_enable_pod_affinity: bool = True
k8s_affinity_topology_key: str = "kubernetes.io/hostname"
```

**Pod Affinity Manifest** (from `kubernetes/helpers.py`):
```python
# All dev containers affine to the same project (same node for shared RWO PVC)
affinity = {
    "podAffinity": {
        "requiredDuringSchedulingIgnoredDuringExecution": [{
            "labelSelector": {
                "matchLabels": {"tesslate.io/project-id": str(project_id)}
            },
            "topologyKey": "kubernetes.io/hostname"
        }]
    }
}
```

**Benefits**:
- All containers share same CSI PVC (btrfs subvolume)
- Faster inter-container communication (same node)
- Volume Hub manages node placement; pod affinity follows

**Trade-offs**:
- ⚠️ Node resource constraints (all pods must fit on one node)
- ⚠️ Single point of failure (node crash affects entire project)

### Configuration

**Required Environment Variables**:
```bash
# Deployment mode
DEPLOYMENT_MODE=kubernetes

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/tesslate

# Auth
SECRET_KEY=your-secret-key-here

# Kubernetes
K8S_DEVSERVER_IMAGE=<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-devserver:latest
K8S_IMAGE_PULL_SECRET=ecr-credentials
K8S_STORAGE_CLASS=tesslate-block-storage

# Volume Hub (3-layer storage)
VOLUME_HUB_ADDRESS=tesslate-volume-hub.kube-system.svc:9750

# Snapshots (Timeline UI, still uses K8s VolumeSnapshot API)
K8S_SNAPSHOT_CLASS=tesslate-ebs-snapshots
K8S_SNAPSHOT_RETENTION_DAYS=30
K8S_MAX_SNAPSHOTS_PER_PROJECT=5
K8S_SNAPSHOT_READY_TIMEOUT_SECONDS=300

# Template Builder (btrfs CoW cloning)
TEMPLATE_BUILD_STORAGE_CLASS=tesslate-btrfs
TEMPLATE_BUILD_NODEOPS_ADDRESS=tesslate-btrfs-csi-node-svc.kube-system.svc:9741

# App Domain
APP_DOMAIN=your-domain.com
COOKIE_DOMAIN=.your-domain.com
```

**Optional Settings**:
```bash
# Kubernetes Advanced
K8S_ENABLE_POD_AFFINITY=true
K8S_ENABLE_NETWORK_POLICIES=true
K8S_PVC_SIZE=5Gi
K8S_HIBERNATION_IDLE_MINUTES=10

# Ingress
K8S_INGRESS_CLASS=nginx
K8S_WILDCARD_TLS_SECRET=tesslate-wildcard-tls
```

### Kubernetes Manifests

**Location**: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/`

**Structure**:
```
k8s/
  base/                       # Base manifests (shared)
    kustomization.yaml
    namespace/                # tesslate namespace
    core/                     # Backend, frontend, cleanup cronjobs
    database/                 # PostgreSQL deployment
    ingress/                  # NGINX Ingress, SSL cert
    security/                 # RBAC, network policies
    storage/                  # VolumeSnapshotClass (btrfs CSI snapshots)

  overlays/
    minikube/                 # Local dev patches
      kustomization.yaml
      backend-patch.yaml      # K8S_DEVSERVER_IMAGE=local
      secrets/                # Generated from .env.minikube

    aws/                      # Production patches
      kustomization.yaml
      backend-patch.yaml      # ECR image, real S3
      secrets/                # Generated from .env.production
```

**Deploy**:
```bash
# Minikube (local)
kubectl apply -k k8s/overlays/minikube

# AWS EKS (production)
kubectl apply -k k8s/overlays/aws
```

## Configuration Differences Table

| Setting | Docker Mode | Kubernetes Mode (Minikube) | Kubernetes Mode (AWS EKS) |
|---------|-------------|----------------------------|---------------------------|
| **DEPLOYMENT_MODE** | `docker` | `kubernetes` | `kubernetes` |
| **DEV_SERVER_BASE_URL** | `http://localhost` | N/A | N/A |
| **K8S_DEVSERVER_IMAGE** | N/A | `tesslate-devserver:latest` | `<ECR>.../tesslate-devserver:latest` |
| **K8S_IMAGE_PULL_SECRET** | N/A | `` (empty - local image) | `ecr-credentials` |
| **K8S_STORAGE_CLASS** | N/A | `standard` (minikube) | `tesslate-block-storage` |
| **K8S_SNAPSHOT_CLASS** | N/A | `tesslate-btrfs-snapshots` | `tesslate-ebs-snapshots` |
| **VOLUME_HUB_ADDRESS** | N/A | `tesslate-volume-hub.kube-system.svc:9750` | `tesslate-volume-hub.kube-system.svc:9750` |
| **TEMPLATE_BUILD_STORAGE_CLASS** | N/A | `tesslate-btrfs` | `tesslate-btrfs` |
| **APP_DOMAIN** | `localhost` | `localhost` | `your-domain.com` |
| **COOKIE_DOMAIN** | `` (empty) | `` (empty) | `.your-domain.com` |
| **K8S_WILDCARD_TLS_SECRET** | N/A | `` (no TLS) | `tesslate-wildcard-tls` |

## Environment Variable Mapping

### Docker Mode `.env`

```bash
# Deployment
DEPLOYMENT_MODE=docker
DEV_SERVER_BASE_URL=http://localhost

# Database
DATABASE_URL=postgresql+asyncpg://tesslate:tesslate@postgres:5432/tesslate

# Auth
SECRET_KEY=your-secret-key-dev

# CORS
CORS_ORIGINS=http://localhost:3000,http://studio.localhost
APP_DOMAIN=localhost

# OAuth (optional)
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
GITHUB_OAUTH_REDIRECT_URI=http://localhost:3000/oauth/callback
```

### Kubernetes Minikube `.env.minikube`

```bash
# Deployment
DEPLOYMENT_MODE=kubernetes

# Database (in-cluster)
DATABASE_URL=postgresql+asyncpg://tesslate:tesslate@postgres:5432/tesslate

# Auth
SECRET_KEY=your-secret-key-dev

# Kubernetes
K8S_DEVSERVER_IMAGE=tesslate-devserver:latest
K8S_IMAGE_PULL_SECRET=
K8S_STORAGE_CLASS=standard

# Volume Hub
VOLUME_HUB_ADDRESS=tesslate-volume-hub.kube-system.svc:9750

# Snapshots (Timeline UI)
K8S_SNAPSHOT_CLASS=tesslate-btrfs-snapshots
K8S_SNAPSHOT_RETENTION_DAYS=30
K8S_MAX_SNAPSHOTS_PER_PROJECT=5

# Template Builder
TEMPLATE_BUILD_STORAGE_CLASS=tesslate-btrfs

# App Domain
APP_DOMAIN=localhost
COOKIE_DOMAIN=

# CORS
CORS_ORIGINS=http://localhost:5000,http://studio.localhost
```

### Kubernetes AWS EKS `.env.production`

```bash
# Deployment
DEPLOYMENT_MODE=kubernetes

# Database (RDS or in-cluster)
DATABASE_URL=postgresql+asyncpg://tesslate:STRONG_PASSWORD@tesslate-db.xxxx.us-east-1.rds.amazonaws.com:5432/tesslate

# Auth
SECRET_KEY=STRONG_RANDOM_SECRET_KEY_PRODUCTION

# Kubernetes
K8S_DEVSERVER_IMAGE=<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-devserver:latest
K8S_IMAGE_PULL_SECRET=ecr-credentials
K8S_STORAGE_CLASS=tesslate-block-storage

# Volume Hub (3-layer storage)
VOLUME_HUB_ADDRESS=tesslate-volume-hub.kube-system.svc:9750

# Snapshots (Timeline UI)
K8S_SNAPSHOT_CLASS=tesslate-ebs-snapshots
K8S_SNAPSHOT_RETENTION_DAYS=30
K8S_MAX_SNAPSHOTS_PER_PROJECT=5
K8S_SNAPSHOT_READY_TIMEOUT_SECONDS=300

# Template Builder
TEMPLATE_BUILD_STORAGE_CLASS=tesslate-btrfs
TEMPLATE_BUILD_NODEOPS_ADDRESS=tesslate-btrfs-csi-node-svc.kube-system.svc:9741

# App Domain
APP_DOMAIN=your-domain.com
COOKIE_DOMAIN=.your-domain.com
COOKIE_SECURE=true

# CORS
CORS_ORIGINS=https://your-domain.com,https://www.your-domain.com

# Ingress
K8S_WILDCARD_TLS_SECRET=tesslate-wildcard-tls

# OAuth (production credentials)
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
GITHUB_OAUTH_REDIRECT_URI=https://your-domain.com/oauth/callback
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_OAUTH_REDIRECT_URI=https://your-domain.com/oauth/callback

# Stripe (production)
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

## Switching Between Modes

### Code Changes Required

**NONE** - The orchestrator automatically adapts based on `DEPLOYMENT_MODE`.

**Example** (from `routers/projects.py`):
```python
from app.services.orchestration import get_orchestrator

# This returns the correct orchestrator based on deployment mode
orchestrator = get_orchestrator()

# Works in both modes
await orchestrator.start_project(project_id, db)
await orchestrator.write_file(project_id, path, content)
```

### Infrastructure Changes Required

**Docker → Kubernetes**:
1. Set up Kubernetes cluster (Minikube, EKS, GKE, etc.)
2. Deploy btrfs CSI driver + Volume Hub (kube-system)
3. Create VolumeSnapshotClass (btrfs-backed)
4. Build and push images to registry (devserver, backend, frontend)
5. Create Kubernetes manifests (or use provided in `k8s/`)
6. Deploy with `kubectl apply -k k8s/overlays/{env}`
7. Update `.env` with K8s-specific settings (Volume Hub address, template builder, etc.)

**Kubernetes → Docker**:
1. ✅ Stop Kubernetes cluster
2. ✅ Update `.env` with `DEPLOYMENT_MODE=docker`
3. ✅ Start Docker Compose: `docker-compose up`
4. ✅ Project files in `users/` directory (no snapshots)

## Choosing a Deployment Mode

### Use Docker Mode When:

- ✅ Developing locally on your machine
- ✅ Testing orchestrator code changes
- ✅ Debugging file operations
- ✅ Working offline (no cloud dependencies)
- ✅ Quick iteration cycles

### Use Kubernetes Mode When:

- ✅ Deploying to production
- ✅ Need horizontal scaling (multiple orchestrator replicas)
- ✅ Want container isolation (NetworkPolicy)
- ✅ Need durable project persistence (Volume Hub + S3 CAS)
- ✅ Want Timeline UI for version history (btrfs-backed VolumeSnapshots)
- ✅ Serving multiple users concurrently
- ✅ Require SSL/TLS certificates

## Related Documentation

- **[system-overview.md](./system-overview.md)** - High-level architecture
- **[data-flow.md](./data-flow.md)** - Request/response patterns
- **[CLAUDE.md](./CLAUDE.md)** - AI agent context for architecture
- **[../../k8s/ARCHITECTURE.md](../../k8s/ARCHITECTURE.md)** - Kubernetes deep dive
- **[../../k8s/QUICKSTART.md](../../k8s/QUICKSTART.md)** - K8s setup guide
