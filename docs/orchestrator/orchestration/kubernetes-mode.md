# Kubernetes Mode - Production Container Orchestration

**File**: `orchestrator/app/services/orchestration/kubernetes_orchestrator.py`

Kubernetes mode provides production-grade container orchestration with namespace isolation, hibernation to S3, and secure multi-tenancy. Each user project gets its own Kubernetes namespace with persistent storage, network policies, and HTTPS ingress.

## Overview

Kubernetes mode is designed for **production deployment** at scale. It supports thousands of concurrent projects with automatic hibernation, resource management, and horizontal scaling of the orchestrator backend.

**Key Features**:
- **Namespace per project** pattern for complete isolation
- **File-manager pod** + **dev container pods** (separate lifecycles)
- **S3 Sandwich pattern** for hibernation/restoration
- **Pod affinity** for shared RWO storage (multi-container projects)
- **NetworkPolicy** for strict network isolation
- **Secure S3 streaming** (credentials never in user pods)
- **Database-based activity tracking** (survives backend restarts)

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                   Tesslate Namespace                         │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Backend Pod (KubernetesOrchestrator)                  │  │
│  │  - Manages all project namespaces                      │  │
│  │  - Has AWS credentials for S3                          │  │
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
│ │ 5Gi RWO    │ │ │ │ 5Gi RWO    │ │ │   [deleted]    │
│ │ /app       │ │ │ │ /app       │ │ │                │
│ └────────────┘ │ │ └────────────┘ │ │   [saved to]   │
│       ▲        │ │       ▲        │ │       ▼        │
│       │ mounts │ │       │ mounts │ │  ┌──────────┐  │
│       │        │ │       │        │ │  │ S3       │  │
│ ┌─────┴──────┐ │ │ ┌─────┴──────┐ │ │  │ Bucket   │  │
│ │ File Mgr   │ │ │ │ File Mgr   │ │ │  │ (ZIP)    │  │
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

S3 LIFECYCLE (Hibernation):
  1. User leaves or idle timeout → backend zips /app via file-manager
  2. Backend uploads to S3 (secure streaming, credentials in backend only)
  3. Delete namespace (including PVC)
  4. User returns → create namespace + PVC, download from S3, extract
```

**Why this matters**: Old architecture wrongly used S3 for new project setup. New architecture only uses S3 for hibernation/restoration. Git clone happens in the file-manager pod at a different lifecycle stage.

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

### 5. S3 Sandwich Pattern

The "S3 Sandwich" pattern hibernates idle projects to save resources:

```
┌─────────────────────────────────────────────────────────────┐
│                  ACTIVE STATE                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ Namespace: proj-{uuid}                                │  │
│  │ ├── PVC (5Gi)                                         │  │
│  │ ├── File-manager pod                                  │  │
│  │ └── Dev container pods (if started)                   │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                         │
                         │ Idle 30+ minutes
                         ▼
            ┌─────────────────────────────┐
            │ HIBERNATION (Dehydration)   │
            │                             │
            │ 1. Zip /app in file-manager │
            │ 2. Copy zip from pod        │
            │ 3. Upload to S3 (boto3)     │
            │ 4. Delete namespace         │
            └─────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  HIBERNATED STATE                           │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ S3: tesslate-project-storage-prod/{user}/{proj}.zip   │  │
│  │ (Compressed project files, no dependencies)           │  │
│  └───────────────────────────────────────────────────────┘  │
│  Database: Project.environment_status = 'hibernated'        │
└─────────────────────────────────────────────────────────────┘
                         │
                         │ User returns
                         ▼
            ┌─────────────────────────────┐
            │ RESTORATION (Hydration)     │
            │                             │
            │ 1. Download from S3 (boto3) │
            │ 2. Copy zip to pod          │
            │ 3. Unzip in file-manager    │
            │ 4. Create namespace + PVC   │
            └─────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  ACTIVE STATE                               │
│  (Cycle continues...)                                       │
└─────────────────────────────────────────────────────────────┘
```

**Security: No AWS Credentials in User Pods**

The S3 operations are performed **by the backend pod** using secure streaming:

```python
# Dehydration (Save to S3)
1. Backend: kubectl exec → file-manager: zip /app to /tmp/project.zip
2. Backend: Copy file from pod → backend temp directory (k8s stream API)
3. Backend: Upload to S3 using boto3 (credentials in backend only)
4. Backend: Delete namespace

# Hydration (Restore from S3)
1. Backend: Download from S3 using boto3 → backend temp directory
2. Backend: Copy file to pod → file-manager:/tmp/project.zip (k8s stream API)
3. Backend: kubectl exec → file-manager: unzip to /app
4. Backend: Create namespace + PVC + file-manager
```

**Why this is secure**: AWS credentials never leave the backend pod. User pods cannot access S3 directly. This prevents malicious code in user projects from accessing or deleting other users' projects.

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
success = await orchestrator.hibernate_project(project_id, user_id)
```

**Steps**:
1. **Save to S3** (via `_save_to_s3`):
   - Zip `/app` in file-manager pod (exclude node_modules, .git, etc.)
   - Copy zip from pod to backend temp directory
   - Upload to S3 using boto3
   - Verify upload succeeded
   - Cleanup temp files
2. **Delete namespace**: Cascades to all resources (PVC, pods, services, ingresses)
3. **Update database**: `Project.environment_status = 'hibernated'`, `hibernated_at = now()`

**Security**: If S3 save fails, namespace is NOT deleted (preserves data). Error is raised to user.

### Returning to Hibernated Project (Restore)

```python
namespace = await orchestrator.restore_project(project_id, user_id)
```

**Steps**:
1. **Create namespace** + PVC + file-manager
2. **Restore from S3** (via `_restore_from_s3`):
   - Download zip from S3 to backend temp directory
   - Validate zip is not corrupt (check file count, size)
   - Copy zip to file-manager pod
   - Unzip to `/app`
   - Cleanup temp files
3. **Update database**: `Project.environment_status = 'active'`, `hibernated_at = NULL`

**Critical validation**: If downloaded archive is corrupt (empty or invalid ZIP), the restore FAILS and the project is marked as corrupted. We never fall back to git clone for a hibernated project—this would lose user changes.

### Deleting Project (Permanent)

```python
await orchestrator.delete_project_namespace(project_id, user_id)
```

**Steps**:
1. Check if namespace exists
2. Delete namespace (cascades all resources)
3. **Does NOT** delete S3 archive (may want to restore later)

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

### Cleanup Cronjob

A Kubernetes CronJob runs periodically:

```yaml
# k8s/base/core/cleanup-cronjob.yaml
schedule: "*/10 * * * *"  # Every 10 minutes
command: ["python", "-c", "
  from orchestrator.app.services.orchestration import get_orchestrator;
  import asyncio;
  orchestrator = get_orchestrator();
  asyncio.run(orchestrator.cleanup_idle_environments(30))
"]
```

**Cleanup logic**:
```python
async def cleanup_idle_environments(self, idle_timeout_minutes=30):
    cutoff_time = now() - timedelta(minutes=idle_timeout_minutes)

    # Find projects where last_activity < cutoff_time and environment_status='active'
    idle_projects = await db.query(Project).filter(
        Project.environment_status == 'active',
        or_(Project.last_activity < cutoff_time, Project.last_activity.is_(None))
    ).all()

    for project in idle_projects:
        # Hibernate project (S3 save + delete namespace)
        await self.hibernate_project(project.id, project.owner_id)

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
K8S_PVC_SIZE=5Gi
K8S_PVC_ACCESS_MODE=ReadWriteOnce

# S3 Sandwich
K8S_USE_S3_STORAGE=true
S3_BUCKET_NAME=tesslate-project-storage-prod
S3_ENDPOINT_URL=https://s3.us-east-1.amazonaws.com
S3_REGION=us-east-1

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

### S3 Hibernation Failures

**Problem**: Hibernation fails with "corrupt archive" or "upload failed"

**Debug**:
```bash
# Check backend pod logs
kubectl logs -n tesslate deployment/tesslate-backend

# Verify S3 credentials
kubectl exec -n tesslate deployment/tesslate-backend -- env | grep AWS

# Test S3 access
kubectl exec -n tesslate deployment/tesslate-backend -- \
  python -c "import boto3; print(boto3.client('s3').list_buckets())"
```

**Common causes**:
- Backend doesn't have S3 credentials
- S3 bucket doesn't exist or wrong region
- File-manager pod not found (project environment not created)
- Zip command failed (out of space, permission denied)

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
✅ **Cost-efficient**: Hibernation to S3 saves resources
✅ **Isolated**: Namespace + NetworkPolicy = strong multi-tenancy
✅ **Secure**: AWS credentials never exposed to user pods
✅ **Resilient**: Database-based tracking, survives backend restarts

### Limitations

❌ **Complex**: More moving parts than Docker mode
❌ **Slower startup**: Pod scheduling, image pulling, PVC mounting
❌ **RWO constraint**: Multi-container projects need pod affinity (same node)
❌ **S3 dependency**: Hibernation requires S3 (or MinIO)

## Next Steps

- See [kubernetes-client.md](./kubernetes-client.md) for K8s API wrapper details
- See [kubernetes-helpers.md](./kubernetes-helpers.md) for manifest generation
- Compare with [docker-mode.md](./docker-mode.md) for local development
