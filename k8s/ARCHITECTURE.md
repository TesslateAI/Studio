# Tesslate Kubernetes Architecture

Complete specification for running Tesslate Studio on Kubernetes.

## Table of Contents

1. [Overview](#overview)
2. [Core Design Principles](#core-design-principles)
3. [Project Lifecycle](#project-lifecycle)
4. [Container Lifecycle](#container-lifecycle)
5. [File Manager Pod](#file-manager-pod)
6. [S3 Hibernation Pattern](#s3-hibernation-pattern)
7. [Resource Manifests](#resource-manifests)
8. [Configuration Reference](#configuration-reference)
9. [Directory Structure](#directory-structure)
10. [Deployment Guide](#deployment-guide)

---

## Overview

Tesslate Studio is an AI-powered web application builder. The Kubernetes deployment uses a **lifecycle separation** architecture that mirrors Docker's correct behavior:

| Concern | Docker Mode | Kubernetes Mode |
|---------|-------------|-----------------|
| Project Storage | Local filesystem | PVC + file-manager pod |
| File Operations | Direct filesystem | kubectl exec into file-manager |
| Container Start | docker-compose up | Create Deployment + Service + Ingress |
| Container Stop | docker-compose stop | Delete Deployment (files persist) |
| Hibernation | N/A (files persist locally) | Zip to S3, delete namespace |

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         NGINX Ingress Controller                        │
│                    (routes *.localhost / *.domain.com)                  │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
         ┌──────────────────────────┼──────────────────────────────────┐
         │                          │                                  │
         ▼                          ▼                                  ▼
┌─────────────────┐   ┌─────────────────────┐   ┌────────────────────────────┐
│    Frontend     │   │      Backend        │   │     User Project           │
│   (NGINX/80)    │   │   (FastAPI/8000)    │   │       Namespace            │
│                 │   │                     │   │    (proj-{uuid})           │
│  React + Vite   │   │  Orchestrator       │   │                            │
│  Static build   │   │  AI Agents          │   │  ┌──────────────────────┐  │
└─────────────────┘   └──────────┬──────────┘   │  │  file-manager pod    │  │
                                 │              │  │  (always running)    │  │
                                 │              │  │  - git clone         │  │
                                 │              │  - file read/write     │  │
                                 │              │  └──────────────────────┘  │
                                 │              │                            │
                                 │              │  ┌──────────────────────┐  │
                                 │              │  │  dev-container pods  │  │
                                 │              │  │  (when started)      │  │
                                 │              │  │  - vite/next.js/etc  │  │
                                 │              │  └──────────────────────┘  │
                                 │              │                            │
                                 │              │  ┌──────────────────────┐  │
                                 │              │  │        PVC           │  │
                                 │              │  │  (shared storage)    │  │
                                 │              │  │  /app/{container}/   │  │
                                 │              │  └──────────────────────┘  │
                                 │              └────────────────────────────┘
                                 │
                      ┌──────────┴──────────┐
                      │                     │
                      ▼                     ▼
             ┌─────────────────┐   ┌─────────────────┐
             │   PostgreSQL    │   │     MinIO       │
             │   (Database)    │   │   (S3 Storage)  │
             │                 │   │                 │
             │  Users, Projects│   │ Project Archives│
             │  Chats, Agents  │   │  (hibernation)  │
             └─────────────────┘   └─────────────────┘
```

---

## Core Design Principles

### 1. Lifecycle Separation

**File lifecycle is SEPARATE from container lifecycle:**

```
PROJECT LIFECYCLE (namespace + storage)
├── Open Project       → Create namespace + PVC + file-manager pod
├── Leave Project      → S3 dehydration → Delete namespace
└── Return to Project  → Create namespace + PVC → S3 hydration

CONTAINER LIFECYCLE (per container)
├── Add to Graph       → Clone template files to /<container-dir>/
├── Start Container    → Create Deployment + Service + Ingress
└── Stop Container     → Delete Deployment (files persist on PVC)
```

### 2. S3 is ONLY for Hibernation

S3 storage is **NOT** used for:
- New project template setup
- Initial file population
- Container startup

S3 storage is **ONLY** used for:
- Saving project state when user leaves (hibernation)
- Restoring project state when user returns (restoration)

### 3. File Manager Pod

Since K8s file operations require `kubectl exec` into a running pod, each project has a **persistent file-manager pod** that:
- Stays running while project is open (even if no dev containers are started)
- Handles git clone operations when containers are added to graph
- Handles file read/write for the code editor
- Is deleted only when project is hibernated

---

## Project Lifecycle

### State Diagram

```
                    ┌─────────────────┐
                    │                 │
                    │     CREATED     │ ← Project exists in database
                    │   (no storage)  │   but no K8s resources
                    │                 │
                    └────────┬────────┘
                             │
                             │ User opens project in builder
                             │ ensure_project_environment()
                             ▼
                    ┌─────────────────┐
                    │                 │
                    │     ACTIVE      │ ← Namespace + PVC + file-manager
                    │  (environment   │   User can add containers,
                    │    ready)       │   edit files, run commands
                    │                 │
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
              │ User leaves                 │ Container added to graph
              │ OR idle timeout             │ initialize_container_files()
              │ hibernate_project()         │
              ▼                             ▼
     ┌─────────────────┐           ┌─────────────────┐
     │                 │           │                 │
     │   HIBERNATED    │           │     ACTIVE      │
     │  (S3 archive,   │           │  + containers   │
     │  no K8s)        │           │                 │
     │                 │           └─────────────────┘
     └────────┬────────┘
              │
              │ User returns to project
              │ restore_project()
              ▼
     ┌─────────────────┐
     │                 │
     │     ACTIVE      │ ← Restored from S3
     │   (containers   │   Containers NOT running
     │    stopped)     │   User must start manually
     │                 │
     └─────────────────┘
```

### 1. Project Open Flow

When a user opens a project in the builder:

```
User opens project in builder
  ↓
Backend: ensure_project_environment(project_id, user_id)
  │
  ├── 1. Create namespace: proj-{project-uuid}
  │
  ├── 2. Create NetworkPolicy (isolation)
  │
  ├── 3. Create PVC: project-storage
  │       └── 5Gi block storage, RWO access mode
  │
  ├── 4. Copy S3 credentials secret (from tesslate namespace)
  │
  └── 5. Create file-manager Deployment (always running)
          └── Mounts PVC at /app
          └── Runs: tail -f /dev/null (keep alive)
```

**Result:** User can now:
- Add containers to architecture graph
- View/edit files in Code tab
- Run commands in terminal

### 2. Add Container to Graph Flow

When a user adds a container to the architecture graph:

```
User adds container (POST /containers)
  ↓
Backend: initialize_container_files(container, base_config)
  │
  ├── 1. Get file-manager pod name
  │
  ├── 2. Exec into file-manager pod:
  │       mkdir -p /app/{container-directory}
  │
  ├── 3. Exec into file-manager pod:
  │       git clone {base-git-url} /app/{container-directory}
  │       OR
  │       cp -r /template/. /app/{container-directory}
  │
  ├── 4. (Optional) Exec into file-manager pod:
  │       cd /app/{container-directory} && npm install
  │
  └── 5. Update container record:
          status = "stopped"
          files_ready = True
```

**Key:** Files are populated when container is **ADDED**, not when started.

### 3. Start Container Flow

When a user clicks "Start" on a container:

```
User starts container (POST /containers/{id}/start)
  ↓
Backend: start_container(container, project, user_id)
  │
  ├── 1. Read base config for port + startup command
  │       (e.g., Next.js: port=3000, cmd="npm run dev")
  │
  ├── 2. Create Deployment: dev-{container-directory}
  │       └── Image: tesslate-devserver:latest
  │       └── Command: npm run dev (from base config)
  │       └── Port: 3000 (from base config)
  │       └── Volume: PVC mounted at /app/{container-directory}
  │       └── WorkingDir: /app/{container-directory}
  │       └── NO init containers needed - files already exist!
  │
  ├── 3. Create Service: dev-{container-directory}
  │       └── Port: {base-config-port}
  │
  ├── 4. Create Ingress: dev-{container-directory}
  │       └── Host: {container}.{project-slug}.{domain}
  │
  └── 5. Update container record:
          status = "running"
          preview_url = "http://{container}.{project-slug}.localhost"
```

**No init containers needed** - files already exist on PVC from step 2!

### 4. Stop Container Flow

When a user clicks "Stop" on a container:

```
User stops container (POST /containers/{id}/stop)
  ↓
Backend: stop_container(container, namespace)
  │
  ├── 1. Delete Deployment: dev-{container-directory}
  │
  ├── 2. Delete Service: dev-{container-directory}
  │
  ├── 3. Delete Ingress: dev-{container-directory}
  │
  └── 4. Update container record:
          status = "stopped"
```

**Files persist** on PVC via file-manager pod.

---

## Container Lifecycle

### Container States

```
┌─────────────┐     initialize_container_files()     ┌─────────────┐
│             │ ─────────────────────────────────▶   │             │
│   pending   │                                      │   stopped   │
│  (no files) │                                      │ (has files) │
│             │                                      │             │
└─────────────┘                                      └──────┬──────┘
                                                           │
                                              start_container()
                                                           │
                                                           ▼
                                                    ┌─────────────┐
                                                    │             │
                                                    │   running   │
                                                    │  (pod up)   │
                                                    │             │
                                                    └──────┬──────┘
                                                           │
                                              stop_container()
                                                           │
                                                           ▼
                                                    ┌─────────────┐
                                                    │             │
                                                    │   stopped   │
                                                    │ (has files) │
                                                    │             │
                                                    └─────────────┘
```

### Multiple Containers in One Project

All containers in a project share the same PVC:

```
PVC: project-storage (mounted at /app)
├── frontend/          ← Container 1 files (e.g., Next.js)
│   ├── package.json
│   ├── src/
│   └── ...
├── backend/           ← Container 2 files (e.g., FastAPI)
│   ├── requirements.txt
│   ├── app/
│   └── ...
└── database/          ← Container 3 (e.g., PostgreSQL)
    └── data/
```

**Pod Affinity:** All container pods must run on the same node to share RWO storage:

```yaml
affinity:
  podAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchLabels:
          tesslate.io/project-id: "{uuid}"
      topologyKey: kubernetes.io/hostname
```

---

## File Manager Pod

The file-manager pod is the key to the new architecture. It enables file operations without having a dev server running.

### Purpose

1. **File Operations** - Read/write files for code editor
2. **Git Clone** - Clone templates when containers added to graph
3. **Command Execution** - Run npm install, etc.
4. **Keep PVC Mounted** - Prevent PVC from becoming unbound

### Deployment Manifest

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: file-manager
  namespace: proj-{project-uuid}
  labels:
    app: file-manager
    tesslate.io/project-id: "{project-uuid}"
    tesslate.io/component: file-manager
spec:
  replicas: 1
  selector:
    matchLabels:
      app: file-manager
  template:
    metadata:
      labels:
        app: file-manager
        tesslate.io/project-id: "{project-uuid}"
        tesslate.io/component: file-manager
    spec:
      containers:
      - name: file-manager
        image: tesslate-devserver:latest
        imagePullPolicy: Never  # minikube: Never, prod: IfNotPresent
        command: ["tail", "-f", "/dev/null"]  # Keep alive
        workingDir: /app
        volumeMounts:
        - name: project-storage
          mountPath: /app
        resources:
          requests:
            memory: "64Mi"
            cpu: "50m"
          limits:
            memory: "256Mi"
            cpu: "200m"
      volumes:
      - name: project-storage
        persistentVolumeClaim:
          claimName: project-storage
```

### Operations via File Manager

**Read File:**
```python
async def read_file(namespace: str, path: str) -> str:
    pod = await get_file_manager_pod(namespace)
    result = await exec_in_pod(
        namespace=namespace,
        pod_name=pod,
        command=["cat", f"/app/{path}"]
    )
    return result.stdout
```

**Write File:**
```python
async def write_file(namespace: str, path: str, content: str) -> None:
    pod = await get_file_manager_pod(namespace)
    # Use base64 to handle special characters
    encoded = base64.b64encode(content.encode()).decode()
    await exec_in_pod(
        namespace=namespace,
        pod_name=pod,
        command=["sh", "-c", f"echo {encoded} | base64 -d > /app/{path}"]
    )
```

**Git Clone:**
```python
async def clone_template(namespace: str, git_url: str, directory: str) -> None:
    pod = await get_file_manager_pod(namespace)
    await exec_in_pod(
        namespace=namespace,
        pod_name=pod,
        command=["sh", "-c", f"""
            mkdir -p /app/{directory}
            git clone --depth 1 {git_url} /app/{directory}
            cd /app/{directory}
            rm -rf .git
            npm install 2>/dev/null || true
        """]
    )
```

---

## S3 Hibernation Pattern

S3 is used **ONLY** for hibernation/restoration - saving project state when users leave and restoring when they return.

### When Hibernation Happens

1. **User explicitly leaves** - Closes project, navigates away
2. **Idle timeout** - No activity for X minutes (configurable)
3. **Manual trigger** - Admin hibernates inactive projects

### Hibernation Flow

```
User leaves project OR idle timeout
  ↓
Backend: hibernate_project(project, namespace)
  │
  ├── 1. Get file-manager pod name
  │
  ├── 2. Exec into file-manager pod:
  │       cd /app
  │       zip -r /tmp/project.zip . \
  │         -x "node_modules/*" \
  │         -x ".git/*" \
  │         -x "__pycache__/*"
  │
  ├── 3. Exec into file-manager pod:
  │       Upload zip to S3:
  │       s3://{bucket}/projects/{user_id}/{project_id}/latest.zip
  │
  ├── 4. Delete namespace (cascades all resources)
  │       kubectl delete namespace proj-{uuid}
  │
  └── 5. Update project record:
          status = "hibernated"
          hibernated_at = now()
```

### Restoration Flow

```
User opens hibernated project
  ↓
Backend: restore_project(project, user_id)
  │
  ├── 1. Create namespace + PVC + file-manager
  │       (same as ensure_project_environment)
  │
  ├── 2. Wait for file-manager pod to be ready
  │
  ├── 3. Exec into file-manager pod:
  │       Download from S3:
  │       s3://{bucket}/projects/{user_id}/{project_id}/latest.zip
  │
  ├── 4. Exec into file-manager pod:
  │       unzip -o /tmp/project.zip -d /app
  │
  ├── 5. Update project record:
  │       status = "active"
  │       hibernated_at = null
  │
  └── 6. Return to user
          (containers NOT running - user must start manually)
```

### S3 Path Structure

```
s3://tesslate-projects/
└── projects/
    └── {user_id}/
        └── {project_id}/
            └── latest.zip
```

---

## Resource Manifests

### Dev Container Deployment

When a user starts a container, this deployment is created:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dev-{container-directory}
  namespace: proj-{project-uuid}
  labels:
    app: dev-container
    tesslate.io/project-id: "{project-uuid}"
    tesslate.io/container-id: "{container-uuid}"
    tesslate.io/container-directory: "{container-directory}"
spec:
  replicas: 1
  selector:
    matchLabels:
      tesslate.io/container-id: "{container-uuid}"
  template:
    metadata:
      labels:
        app: dev-container
        tesslate.io/project-id: "{project-uuid}"
        tesslate.io/container-id: "{container-uuid}"
    spec:
      affinity:
        podAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchLabels:
                tesslate.io/project-id: "{project-uuid}"
            topologyKey: kubernetes.io/hostname
      containers:
      - name: dev-server
        image: tesslate-devserver:latest
        imagePullPolicy: Never  # minikube
        command: ["sh", "-c"]
        args:
        - |
          cd /app/{container-directory}
          {startup-command}  # e.g., "npm run dev"
        ports:
        - containerPort: {port}  # e.g., 3000
          name: http
        workingDir: /app/{container-directory}
        volumeMounts:
        - name: project-storage
          mountPath: /app
        env:
        - name: HOST
          value: "0.0.0.0"
        - name: PORT
          value: "{port}"
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
      volumes:
      - name: project-storage
        persistentVolumeClaim:
          claimName: project-storage
```

### Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: dev-{container-directory}
  namespace: proj-{project-uuid}
  labels:
    tesslate.io/project-id: "{project-uuid}"
    tesslate.io/container-id: "{container-uuid}"
spec:
  selector:
    tesslate.io/container-id: "{container-uuid}"
  ports:
  - port: {port}
    targetPort: {port}
    protocol: TCP
  type: ClusterIP
```

### Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: dev-{container-directory}
  namespace: proj-{project-uuid}
  labels:
    tesslate.io/project-id: "{project-uuid}"
    tesslate.io/container-id: "{container-uuid}"
spec:
  ingressClassName: nginx
  rules:
  - host: {container-directory}.{project-slug}.localhost  # or .domain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: dev-{container-directory}
            port:
              number: {port}
```

### PVC

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: project-storage
  namespace: proj-{project-uuid}
  labels:
    tesslate.io/project-id: "{project-uuid}"
spec:
  accessModes:
  - ReadWriteOnce
  storageClassName: tesslate-block-storage  # mapped per environment
  resources:
    requests:
      storage: 5Gi
```

### Network Policy

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: project-isolation
  namespace: proj-{project-uuid}
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # Allow ingress controller
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: ingress-nginx
  # Allow from tesslate backend (for file operations)
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: tesslate
  egress:
  # Allow DNS
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: UDP
      port: 53
  # Allow HTTPS (npm, git)
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
    ports:
    - protocol: TCP
      port: 443
  # Allow MinIO (S3)
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: minio-system
```

---

## Configuration Reference

### Environment Variables (config.py)

```python
# Core K8s settings
k8s_devserver_image: str = "tesslate-devserver:latest"
k8s_image_pull_policy: str = "IfNotPresent"  # Never for minikube
k8s_image_pull_secret: str = ""  # Empty for minikube
k8s_storage_class: str = "tesslate-block-storage"
k8s_default_namespace: str = "tesslate"
k8s_ingress_class: str = "nginx"

# PVC settings
k8s_pvc_size: str = "5Gi"
k8s_pvc_access_mode: str = "ReadWriteOnce"

# Pod affinity (for shared PVC)
k8s_enable_pod_affinity: bool = True
k8s_affinity_topology_key: str = "kubernetes.io/hostname"

# S3 for hibernation
s3_access_key_id: str = ""
s3_secret_access_key: str = ""
s3_bucket_name: str = "tesslate-projects"
s3_endpoint_url: str = ""  # Empty for AWS, set for MinIO
s3_region: str = "us-east-1"
k8s_s3_credentials_secret: str = "s3-credentials"

# Hibernation settings
k8s_hibernation_idle_minutes: int = 30
```

### Minikube Overrides (backend-patch.yaml)

```yaml
env:
- name: K8S_DEVSERVER_IMAGE
  value: "tesslate-devserver:latest"
- name: K8S_IMAGE_PULL_SECRET
  value: ""
- name: K8S_IMAGE_PULL_POLICY
  value: "Never"
```

---

## Directory Structure

```
k8s/
├── ARCHITECTURE.md           # This file (full specification)
├── QUICKSTART.md             # Getting started guide
├── .env.example              # Template for credentials
├── .env.minikube             # Local credentials (gitignored)
│
├── base/                     # Kustomize base
│   ├── kustomization.yaml
│   ├── namespace/
│   │   └── tesslate.yaml
│   ├── core/
│   │   ├── backend-deployment.yaml
│   │   ├── backend-service.yaml
│   │   ├── frontend-deployment.yaml
│   │   ├── frontend-service.yaml
│   │   └── cleanup-cronjob.yaml
│   ├── database/
│   │   ├── postgres-deployment.yaml
│   │   ├── postgres-service.yaml
│   │   └── postgres-pvc.yaml
│   ├── ingress/
│   │   └── main-ingress.yaml
│   ├── security/
│   │   ├── rbac.yaml
│   │   └── network-policies.yaml
│   └── minio/
│       ├── minio-namespace.yaml
│       ├── minio-deployment.yaml
│       ├── minio-service.yaml
│       ├── minio-pvc.yaml
│       └── minio-init-job.yaml
│
├── overlays/
│   ├── minikube/
│   │   ├── kustomization.yaml
│   │   ├── storage-class.yaml
│   │   ├── backend-patch.yaml
│   │   ├── frontend-patch.yaml
│   │   ├── ingress-patch.yaml
│   │   └── secrets/           # Generated, gitignored
│   │       ├── postgres-secret.yaml
│   │       ├── s3-credentials.yaml
│   │       └── app-secrets.yaml
│   └── production/
│       └── ... (DigitalOcean config)
│
└── scripts/
    ├── generate-secrets-from-env.sh
    └── deployment/
        ├── build-push-images.sh
        └── deploy-application.sh
```

---

## Deployment Guide

### Minikube (Local Development)

```bash
# 1. Start minikube
minikube start -p tesslate --driver=docker --memory=4096
minikube -p tesslate addons enable ingress

# 2. Build images
eval $(minikube -p tesslate docker-env)
docker build -t tesslate-backend:latest -f orchestrator/Dockerfile .
docker build -t tesslate-frontend:latest -f app/Dockerfile.prod app/
docker build -t tesslate-devserver:latest -f devserver/Dockerfile devserver/

# 3. Generate secrets
vim k8s/.env.minikube  # Edit credentials
bash k8s/scripts/generate-secrets-from-env.sh minikube

# 4. Deploy
kubectl apply -k k8s/overlays/minikube

# 5. Start tunnel
minikube -p tesslate tunnel

# 6. Access
open http://localhost
```

### Production (DigitalOcean)

```bash
# 1. Connect to cluster
doctl kubernetes cluster kubeconfig save tesslate-studio-nyc2

# 2. Build and push images
cd k8s/scripts/deployment
./build-push-images.sh

# 3. Generate secrets
vim k8s/.env.production
bash k8s/scripts/generate-secrets-from-env.sh production

# 4. Deploy
kubectl apply -k k8s/overlays/production
```

---

## Troubleshooting

### File Manager Pod Not Ready

```bash
# Check pod status
kubectl get pods -n proj-{uuid} -l app=file-manager

# Check pod logs
kubectl logs -n proj-{uuid} -l app=file-manager

# Check PVC is bound
kubectl get pvc -n proj-{uuid}
```

### Container Won't Start

```bash
# Check deployment
kubectl describe deployment dev-{container} -n proj-{uuid}

# Check pod events
kubectl get events -n proj-{uuid} --sort-by='.lastTimestamp'

# Check files exist
kubectl exec -n proj-{uuid} deploy/file-manager -- ls -la /app/{container}
```

### Files Not Showing in Code Tab

```bash
# Verify file-manager is running
kubectl get pods -n proj-{uuid} -l app=file-manager

# Test file read
kubectl exec -n proj-{uuid} deploy/file-manager -- cat /app/{container}/package.json
```

### Ingress Not Working

```bash
# Check ingress
kubectl get ingress -n proj-{uuid}

# Check ingress controller
kubectl logs -n ingress-nginx deploy/ingress-nginx-controller | tail -50

# Ensure minikube tunnel is running (local)
minikube -p tesslate tunnel
```

---

## Success Criteria

After implementing this architecture:

1. **File population separate from container start** - Files appear when container added to graph
2. **Files visible in Code tab** - file-manager pod enables file operations before starting containers
3. **Correct startup command** - Uses base config (Next.js uses `npm run dev`, not Vite command)
4. **Correct port** - Service/Ingress use port from base config (3000 for Next.js, 5173 for Vite)
5. **Stop doesn't lose files** - PVC persists via file-manager until hibernation
6. **Hibernation works** - S3 upload on leave, download on return
7. **Multiple containers work** - Pod affinity ensures shared PVC access
