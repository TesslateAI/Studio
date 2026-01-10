# Deployment Modes Documentation

This document explains Tesslate Studio's two deployment modes: **Docker mode** (local development) and **Kubernetes mode** (production). Each mode has different routing, storage, and configuration requirements.

**Visual Reference**: For deployment pipeline diagrams, see `diagrams/deployment-pipeline.mmd` (when created).

## Overview

Tesslate Studio supports two deployment modes configured via the `DEPLOYMENT_MODE` environment variable:

| Mode | Use Case | Routing | Storage | Complexity |
|------|----------|---------|---------|------------|
| **Docker** | Local development | Traefik (*.localhost) | Local filesystem | Low |
| **Kubernetes** | Production (cloud) | NGINX Ingress | S3 + PVC (S3 Sandwich) | High |

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
- ❌ S3 Sandwich pattern (no hydration/dehydration)
- ❌ Horizontal scaling (single orchestrator instance)
- ❌ Automatic SSL certificates (localhost only)

**What Docker Mode IS For**:
- ✅ Local development and testing
- ✅ Fast iteration on orchestrator code
- ✅ Simple debugging (files on disk)
- ✅ No cloud dependencies (works offline)

## Kubernetes Mode (Production)

### Overview

Kubernetes mode runs in a K8s cluster with NGINX Ingress for routing and the S3 Sandwich pattern for storage. Each user project gets a dedicated namespace with strict isolation.

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
│  │  PVC (5Gi Block Storage)                       │        │
│  │  - Shared by all pods in namespace             │        │
│  │  - Ephemeral (deleted on project close)        │        │
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
                ┌─────────────────┐
                │   AWS S3 (or    │
                │  DO Spaces /    │
                │    MinIO)       │
                │  Bucket:        │
                │  tesslate-      │
                │  project-       │
                │  storage-prod   │
                └─────────────────┘
```

### Routing (NGINX Ingress)

**Pattern**: Subdomains routed to K8s Services via Ingress

**Examples**:
- Frontend: `https://your-domain.com`
- Backend: `https://api.your-domain.com`
- User project (frontend): `https://frontend.proj-{uuid}.your-domain.com`
- User project (backend): `https://backend.proj-{uuid}.your-domain.com`

**Ingress Configuration** (from `kubernetes/helpers.py`):
```python
def create_ingress_manifest(
    project_id: str,
    container_name: str,
    subdomain: str,
    service_port: int
):
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "name": f"{container_name}-ingress",
            "annotations": {
                "cert-manager.io/cluster-issuer": "letsencrypt-prod",
                "nginx.ingress.kubernetes.io/ssl-redirect": "true",
                "nginx.ingress.kubernetes.io/proxy-hide-headers": "X-Frame-Options",
            }
        },
        "spec": {
            "ingressClassName": "nginx",
            "tls": [{
                "hosts": [f"{subdomain}.proj-{project_id}.your-domain.com"],
                "secretName": "tesslate-wildcard-tls"
            }],
            "rules": [{
                "host": f"{subdomain}.proj-{project_id}.your-domain.com",
                "http": {
                    "paths": [{
                        "path": "/",
                        "pathType": "Prefix",
                        "backend": {
                            "service": {
                                "name": f"{container_name}-service",
                                "port": {"number": service_port}
                            }
                        }
                    }]
                }
            }]
        }
    }
```

**SSL Certificates**:
- Wildcard cert: `*.your-domain.com` (covers all user projects)
- Provisioned via cert-manager + Let's Encrypt
- DNS-01 challenge (Cloudflare API)
- Automatic renewal

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/base/ingress/certificate.yaml`

### Storage (S3 Sandwich Pattern)

**Concept**: Combine S3 durability with PVC performance

**Lifecycle**:
```
┌─────────────────────────────────────────────────────────┐
│  1. PROJECT OPEN (Hydration)                            │
│                                                         │
│  User opens project                                     │
│    ↓                                                    │
│  Create namespace + PVC                                 │
│    ↓                                                    │
│  Init container runs:                                   │
│    - Check if S3 backup exists                          │
│    - If yes: Download from S3 → Unzip to PVC           │
│    - If no: Copy template files to PVC                  │
│    ↓                                                    │
│  File manager pod starts                                │
│    ↓                                                    │
│  Dev containers start (optional)                        │
│                                                         │
│  ✅ Project ready for file operations                   │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  2. RUNTIME (Fast Local I/O)                            │
│                                                         │
│  User edits files via:                                  │
│    - Monaco editor (write_file tool)                    │
│    - Agent commands (bash, git)                         │
│    - Manual uploads                                     │
│    ↓                                                    │
│  File manager pod writes to PVC                         │
│    - Local disk speed (no S3 latency)                   │
│    - All containers share same PVC (pod affinity)       │
│                                                         │
│  ✅ Fast I/O, no network delays                         │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  3. PROJECT CLOSE (Dehydration)                         │
│                                                         │
│  User leaves project OR project idles for 10+ min       │
│    ↓                                                    │
│  PreStop hook runs in file manager pod:                 │
│    - Zip entire project directory                       │
│    - Upload to S3: projects/{user_id}/{project_id}.zip  │
│    - Wait for upload completion                         │
│    ↓                                                    │
│  Delete namespace (cascades to all resources)           │
│    - Pods deleted                                       │
│    - PVC deleted (ephemeral storage)                    │
│                                                         │
│  ✅ Project saved to S3, cluster resources freed        │
└─────────────────────────────────────────────────────────┘
```

**Hydration Script** (Init container):
```bash
#!/bin/bash
# From kubernetes/helpers.py

S3_KEY="projects/${USER_ID}/${PROJECT_ID}.zip"

# Download from S3 if exists
if aws s3 ls "s3://${S3_BUCKET}/${S3_KEY}"; then
  echo "Hydrating project from S3..."
  aws s3 cp "s3://${S3_BUCKET}/${S3_KEY}" /tmp/project.zip
  unzip /tmp/project.zip -d /app
  echo "Hydration complete"
else
  echo "No S3 backup found, using template"
  # Copy template files (handled by orchestrator)
fi
```

**Dehydration Script** (PreStop hook):
```bash
#!/bin/bash
# From kubernetes/helpers.py

S3_KEY="projects/${USER_ID}/${PROJECT_ID}.zip"

echo "Dehydrating project to S3..."

# Zip project (exclude .git to reduce size)
cd /app
zip -r /tmp/project.zip . -x ".git/*"

# Upload to S3
aws s3 cp /tmp/project.zip "s3://${S3_BUCKET}/${S3_KEY}"

echo "Dehydration complete"
```

**Advantages**:
- ✅ Fast I/O (PVC is local disk)
- ✅ Durable (S3 backup prevents data loss)
- ✅ Cost-efficient (ephemeral PVCs deleted when unused)
- ✅ Scalable (projects can move across nodes)

**Disadvantages**:
- ❌ Hydration delay on first access (5-30s depending on project size)
- ❌ Dehydration delay on shutdown (5-30s)
- ❌ S3 storage costs (mitigated by lifecycle policies)

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/s3_manager.py`

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
# PVC (5Gi block storage)
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: project-storage
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: tesslate-block-storage
  resources:
    requests:
      storage: 5Gi

---
# File Manager Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: file-manager
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: file-manager
        image: tesslate-devserver:latest
        volumeMounts:
        - name: project-source
          mountPath: /app
      volumes:
      - name: project-source
        persistentVolumeClaim:
          claimName: project-storage

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
      affinity:  # Pod affinity to share RWO storage
        podAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchLabels:
                app: file-manager
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
          claimName: project-storage

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

**Problem**: Kubernetes PVCs with `ReadWriteOnce` (RWO) can only be mounted by pods on the same node.

**Solution**: Pod affinity ensures all containers in a project run on the same node.

**Configuration** (from `config.py`):
```python
k8s_enable_pod_affinity: bool = True
k8s_affinity_topology_key: str = "kubernetes.io/hostname"
```

**Pod Affinity Manifest** (from `kubernetes/helpers.py`):
```python
# All dev containers affine to file-manager
affinity = {
    "podAffinity": {
        "requiredDuringSchedulingIgnoredDuringExecution": [{
            "labelSelector": {
                "matchLabels": {"app": "file-manager"}
            },
            "topologyKey": "kubernetes.io/hostname"
        }]
    }
}
```

**Benefits**:
- ✅ All containers share same PVC (RWO storage)
- ✅ Faster inter-container communication (same node)
- ✅ Simpler storage management (no need for RWX)

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
K8S_DEVSERVER_IMAGE=registry.digitalocean.com/.../tesslate-devserver:latest
K8S_IMAGE_PULL_SECRET=tesslate-container-registry-nyc3
K8S_STORAGE_CLASS=tesslate-block-storage
K8S_USE_S3_STORAGE=true

# S3
S3_ENDPOINT_URL=https://s3.us-east-1.amazonaws.com
S3_BUCKET_NAME=tesslate-project-storage-prod
S3_ACCESS_KEY_ID=<YOUR_S3_ACCESS_KEY>
S3_SECRET_ACCESS_KEY=<YOUR_S3_SECRET_KEY>
S3_REGION=us-east-1

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
K8S_DEHYDRATION_EXCLUDE_PATTERNS=.git

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
    core/                     # Backend, frontend, cleanup
    database/                 # PostgreSQL deployment
    ingress/                  # NGINX Ingress, SSL cert
    security/                 # RBAC, network policies
    minio/                    # S3-compatible storage (local)

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
| **K8S_USE_S3_STORAGE** | N/A | `true` | `true` |
| **K8S_STORAGE_CLASS** | N/A | `standard` (minikube) | `gp3` (AWS EBS) |
| **S3_ENDPOINT_URL** | N/A | `http://minio:9000` (MinIO) | `https://s3.us-east-1.amazonaws.com` |
| **S3_BUCKET_NAME** | N/A | `tesslate-projects-dev` | `tesslate-project-storage-prod` |
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
K8S_USE_S3_STORAGE=true

# S3 (MinIO)
S3_ENDPOINT_URL=http://minio.minio-system.svc.cluster.local:9000
S3_BUCKET_NAME=tesslate-projects-dev
S3_ACCESS_KEY_ID=minioadmin
S3_SECRET_ACCESS_KEY=minioadmin
S3_REGION=us-east-1

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
K8S_STORAGE_CLASS=gp3
K8S_USE_S3_STORAGE=true

# S3 (AWS S3)
S3_ENDPOINT_URL=https://s3.us-east-1.amazonaws.com
S3_BUCKET_NAME=tesslate-project-storage-prod
S3_ACCESS_KEY_ID=<YOUR_S3_ACCESS_KEY>
S3_SECRET_ACCESS_KEY=<YOUR_S3_SECRET_KEY>
S3_REGION=us-east-1

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
1. ✅ Set up Kubernetes cluster (Minikube, EKS, GKE, etc.)
2. ✅ Configure S3-compatible storage (MinIO, AWS S3, DO Spaces)
3. ✅ Build and push images to registry
4. ✅ Create Kubernetes manifests (or use provided in `k8s/`)
5. ✅ Deploy with `kubectl apply -k k8s/overlays/{env}`
6. ✅ Update `.env` with K8s-specific settings

**Kubernetes → Docker**:
1. ✅ Stop Kubernetes cluster
2. ✅ Update `.env` with `DEPLOYMENT_MODE=docker`
3. ✅ Start Docker Compose: `docker-compose up`
4. ✅ Project files in `users/` directory (no S3)

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
- ✅ Need S3 durability (project persistence)
- ✅ Serving multiple users concurrently
- ✅ Require SSL/TLS certificates

## Related Documentation

- **[system-overview.md](./system-overview.md)** - High-level architecture
- **[data-flow.md](./data-flow.md)** - Request/response patterns
- **[CLAUDE.md](./CLAUDE.md)** - AI agent context for architecture
- **[../../k8s/ARCHITECTURE.md](../../k8s/ARCHITECTURE.md)** - Kubernetes deep dive
- **[../../k8s/QUICKSTART.md](../../k8s/QUICKSTART.md)** - K8s setup guide
