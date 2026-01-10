# Kubernetes Manifest Helpers

**File**: `orchestrator/app/services/orchestration/kubernetes/helpers.py`

This module provides functions for generating Kubernetes manifests (YAML configurations as Python objects). These manifests define the infrastructure for user projects: PVCs, Deployments, Services, Ingresses, and NetworkPolicies.

## Purpose

Instead of maintaining static YAML files or template strings, we generate manifests programmatically. This provides:
- **Type safety**: Python objects with IDE autocomplete
- **Flexibility**: Dynamic configuration based on project requirements
- **Testability**: Easy to unit test manifest generation
- **Maintainability**: Changes propagate consistently

## Manifest Generation Functions

### PVC Manifest

**Function**: `create_pvc_manifest()`

Creates a PersistentVolumeClaim for project file storage.

```python
pvc = create_pvc_manifest(
    namespace="proj-d4f6e8a2-...",
    project_id=UUID("d4f6e8a2-..."),
    user_id=UUID("123e4567-..."),
    storage_class="tesslate-block-storage",
    size="5Gi",
    access_mode="ReadWriteOnce"
)
```

**Generated Manifest**:
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: project-storage
  namespace: proj-d4f6e8a2-...
  labels:
    app.kubernetes.io/managed-by: tesslate-backend
    tesslate.io/project-id: d4f6e8a2-...
    tesslate.io/user-id: 123e4567-...
    tesslate.io/component: storage
spec:
  storageClassName: tesslate-block-storage
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 5Gi
```

**Key Points**:
- Name is always `project-storage` (consistent within namespace)
- `ReadWriteOnce` means only one node can mount (requires pod affinity for multi-container)
- Storage class determines the underlying storage type (SSD, HDD, etc.)

### File-Manager Deployment

**Function**: `create_file_manager_deployment()`

Creates the always-running file-manager pod that handles file operations.

```python
deployment = create_file_manager_deployment(
    namespace="proj-d4f6e8a2-...",
    project_id=UUID("d4f6e8a2-..."),
    user_id=UUID("123e4567-..."),
    image="tesslate-devserver:latest",
    image_pull_policy="IfNotPresent",
    image_pull_secret=None  # or "ecr-credentials"
)
```

**Generated Manifest**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: file-manager
  namespace: proj-d4f6e8a2-...
  labels:
    app.kubernetes.io/managed-by: tesslate-backend
    tesslate.io/project-id: d4f6e8a2-...
    tesslate.io/user-id: 123e4567-...
    tesslate.io/component: file-manager
    app: file-manager
spec:
  replicas: 1
  selector:
    matchLabels:
      app: file-manager
  template:
    metadata:
      labels:
        app: file-manager
        # ... (same labels as deployment)
    spec:
      containers:
        - name: file-manager
          image: tesslate-devserver:latest
          imagePullPolicy: IfNotPresent
          command: ["tail", "-f", "/dev/null"]  # Keep alive
          workingDir: /app
          volumeMounts:
            - name: project-storage
              mountPath: /app
          resources:
            requests:
              memory: "256Mi"
              cpu: "100m"
            limits:
              memory: "1536Mi"  # Enough for npm install
              cpu: "1000m"
      volumes:
        - name: project-storage
          persistentVolumeClaim:
            claimName: project-storage
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
      imagePullSecrets:  # Optional
        - name: ecr-credentials
```

**Key Points**:
- Command `tail -f /dev/null` keeps container alive without consuming resources
- Working directory `/app` matches dev containers (consistency)
- Volume `project-storage` mounted at `/app`
- Security: Runs as user 1000 (non-root)
- Resources: 256Mi-1536Mi RAM (enough for npm install in file-manager)

**Why high memory limit?** Next.js/React projects can use 1GB+ during `npm install`. The file-manager executes `git clone` which may trigger automatic dependency installation in some templates.

### Dev Container Deployment

**Function**: `create_container_deployment()`

Creates a dev server deployment (frontend, backend, etc.).

```python
deployment = create_container_deployment(
    namespace="proj-d4f6e8a2-...",
    project_id=UUID("d4f6e8a2-..."),
    user_id=UUID("123e4567-..."),
    container_id=UUID("c9d1e3f5-..."),
    container_directory="frontend",
    image="tesslate-devserver:latest",
    port=3000,
    startup_command="npm run dev",
    image_pull_policy="IfNotPresent",
    image_pull_secret=None,
    enable_pod_affinity=True,
    affinity_topology_key="kubernetes.io/hostname"
)
```

**Generated Manifest**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dev-frontend
  namespace: proj-d4f6e8a2-...
  labels:
    app.kubernetes.io/managed-by: tesslate-backend
    tesslate.io/project-id: d4f6e8a2-...
    tesslate.io/user-id: 123e4567-...
    tesslate.io/component: dev-container
    tesslate.io/container-id: c9d1e3f5-...
    tesslate.io/container-directory: frontend
    app: dev-container
spec:
  replicas: 1
  selector:
    matchLabels:
      tesslate.io/container-id: c9d1e3f5-...
  template:
    metadata:
      labels:
        # ... (same as deployment + selector labels)
    spec:
      affinity:  # Pod affinity for shared PVC
        podAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchLabels:
                  tesslate.io/project-id: d4f6e8a2-...
              topologyKey: kubernetes.io/hostname
      containers:
        - name: dev-server
          image: tesslate-devserver:latest
          imagePullPolicy: IfNotPresent
          command: ["sh", "-c"]
          args:
            - |
              cd /app/frontend && \
              tmux new-session -d -s main 'npm run dev' && \
              exec tail -f /dev/null
          ports:
            - containerPort: 3000
              name: http
          workingDir: /app/frontend
          volumeMounts:
            - name: project-storage
              mountPath: /app
          env:
            - name: HOST
              value: "0.0.0.0"
            - name: PORT
              value: "3000"
            - name: NODE_ENV
              value: "development"
          resources:
            requests:
              memory: "256Mi"
              cpu: "100m"
            limits:
              memory: "1Gi"
              cpu: "1000m"
          startupProbe:
            httpGet:
              path: /
              port: 3000
            initialDelaySeconds: 5
            periodSeconds: 3
            timeoutSeconds: 5
            failureThreshold: 30  # Allow 90 seconds for npm install
          readinessProbe:
            httpGet:
              path: /
              port: 3000
            initialDelaySeconds: 5
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 3
          livenessProbe:
            httpGet:
              path: /
              port: 3000
            initialDelaySeconds: 30
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
      volumes:
        - name: project-storage
          persistentVolumeClaim:
            claimName: project-storage
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
```

**Key Points**:

**Pod Affinity**: Ensures all containers in the project run on the same node (required for RWO PVC).

**Startup Command**: Uses tmux to run dev server in background session:
```bash
cd /app/frontend && \
tmux new-session -d -s main 'npm run dev' && \
exec tail -f /dev/null
```
- `tmux new-session -d -s main 'npm run dev'`: Start dev server in tmux session "main"
- `exec tail -f /dev/null`: Keep container alive (PID 1 is immortal tail)
- **Why tmux?** Agent can stop/restart dev server without crashing container:
  ```bash
  # Stop dev server
  tmux send-keys -t main C-c

  # Restart dev server
  tmux send-keys -t main 'npm run dev' Enter
  ```

**Probes**:
- **Startup probe**: Waits up to 90 seconds for dev server to start (allows time for npm install)
- **Readiness probe**: Checks if server is ready to accept traffic
- **Liveness probe**: Restarts container if server crashes

**No Init Containers**: Files already exist on PVC from `initialize_container_files()`. No need for init containers!

### Service Manifest

**Function**: `create_service_manifest()`

Creates a ClusterIP service for a dev container.

```python
service = create_service_manifest(
    namespace="proj-d4f6e8a2-...",
    project_id=UUID("d4f6e8a2-..."),
    container_id=UUID("c9d1e3f5-..."),
    container_directory="frontend",
    port=3000
)
```

**Generated Manifest**:
```yaml
apiVersion: v1
kind: Service
metadata:
  name: dev-frontend
  namespace: proj-d4f6e8a2-...
  labels:
    tesslate.io/project-id: d4f6e8a2-...
    tesslate.io/container-id: c9d1e3f5-...
    tesslate.io/container-directory: frontend
spec:
  selector:
    tesslate.io/container-id: c9d1e3f5-...
  ports:
    - port: 3000
      targetPort: 3000
      protocol: TCP
  type: ClusterIP
```

**Key Points**:
- Service name matches deployment name: `dev-{container_directory}`
- Selector uses `container-id` label (matches pods)
- ClusterIP (internal only - ingress provides external access)

### Ingress Manifest

**Function**: `create_ingress_manifest()`

Creates an NGINX Ingress for HTTPS access.

```python
ingress = create_ingress_manifest(
    namespace="proj-d4f6e8a2-...",
    project_id=UUID("d4f6e8a2-..."),
    container_id=UUID("c9d1e3f5-..."),
    container_directory="frontend",
    project_slug="my-app-abc123",
    port=3000,
    domain="your-domain.com",
    ingress_class="nginx",
    tls_secret="tesslate-wildcard-tls"
)
```

**Generated Manifest**:
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: dev-frontend
  namespace: proj-d4f6e8a2-...
  labels:
    tesslate.io/project-id: d4f6e8a2-...
    tesslate.io/container-id: c9d1e3f5-...
    tesslate.io/container-directory: frontend
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

**Key Points**:

**URL Pattern**: `{project-slug}-{container-directory}.{domain}`
- Single subdomain level (for wildcard cert compatibility)
- Example: `my-app-abc123-frontend.your-domain.com`

**Annotations**:
- `proxy-http-version: "1.1"`: Required for WebSocket (HMR)
- `proxy-read-timeout: "3600"`: Long timeout for streaming responses
- `proxy-send-timeout: "3600"`: Long timeout for file uploads

**TLS**: Uses wildcard certificate (`*.your-domain.com`) copied to namespace.

### NetworkPolicy Manifest

**Function**: `create_network_policy_manifest()`

Creates a NetworkPolicy for project isolation.

```python
policy = create_network_policy_manifest(
    namespace="proj-d4f6e8a2-...",
    project_id=UUID("d4f6e8a2-...")
)
```

**Generated Manifest**:
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: project-isolation
  namespace: proj-d4f6e8a2-...
  labels:
    tesslate.io/project-id: d4f6e8a2-...
spec:
  podSelector: {}  # Apply to all pods in namespace
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Allow from NGINX ingress controller
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress-nginx
    # Allow from Tesslate backend (for file operations)
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: tesslate
    # Allow within namespace (inter-container communication)
    - from:
        - podSelector: {}
  egress:
    # Allow DNS (UDP 53)
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: UDP
          port: 53
    # Allow HTTPS (npm, git, external APIs)
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
      ports:
        - protocol: TCP
          port: 443
        - protocol: TCP
          port: 80
    # Allow MinIO (if using local S3)
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: minio-system
```

**Key Points**:

**Ingress Rules**:
- ✅ From NGINX (public access to dev servers)
- ✅ From Tesslate backend (file operations via kubectl exec)
- ✅ Within namespace (frontend → backend, etc.)
- ❌ From other projects (blocked)

**Egress Rules**:
- ✅ DNS queries (for hostname resolution)
- ✅ HTTPS (npm install, git clone, external APIs)
- ✅ HTTP (some npm registries)
- ✅ MinIO (local S3 for development)
- ❌ Direct access to internal services (blocked)

## Pod Affinity Helper

**Function**: `create_pod_affinity_spec()`

Creates pod affinity configuration for multi-container projects.

```python
affinity = create_pod_affinity_spec(
    project_id="d4f6e8a2-...",
    topology_key="kubernetes.io/hostname"
)
```

**Generated**:
```python
client.V1Affinity(
    pod_affinity=client.V1PodAffinity(
        required_during_scheduling_ignored_during_execution=[
            client.V1PodAffinityTerm(
                label_selector=client.V1LabelSelector(
                    match_labels={"tesslate.io/project-id": "d4f6e8a2-..."}
                ),
                topology_key="kubernetes.io/hostname"
            )
        ]
    )
)
```

**Purpose**: Ensures all pods with the same `project-id` label run on the same node, allowing them to share a ReadWriteOnce (RWO) PVC.

**Topology Key**: `kubernetes.io/hostname` means "same node". Alternative: `topology.kubernetes.io/zone` for "same zone".

## Labels Helper

**Function**: `get_standard_labels()`

Generates consistent labels for all resources.

```python
labels = get_standard_labels(
    project_id="d4f6e8a2-...",
    user_id="123e4567-...",
    component="dev-container",
    container_id="c9d1e3f5-...",
    container_directory="frontend"
)
```

**Returns**:
```python
{
    "app.kubernetes.io/managed-by": "tesslate-backend",
    "tesslate.io/project-id": "d4f6e8a2-...",
    "tesslate.io/user-id": "123e4567-...",
    "tesslate.io/component": "dev-container",
    "tesslate.io/container-id": "c9d1e3f5-...",
    "tesslate.io/container-directory": "frontend"
}
```

**Use Cases**:
- Label selectors (find all pods for a project)
- Cleanup (delete all resources with project-id)
- Metrics (group resources by user/project)

## Git Clone Script

**Function**: `generate_git_clone_script()`

Generates a shell script to clone a git repository into a container.

```python
script = generate_git_clone_script(
    git_url="https://github.com/tesslate/next-js-15.git",
    branch="main",
    target_dir="/app/frontend",
    install_deps=False  # Don't install dependencies (done during container startup)
)
```

**Generated Script**:
```bash
#!/bin/sh
set -e

TARGET_DIR="/app/frontend"

echo "[CLONE] ======================================"
echo "[CLONE] Cloning repository"
echo "[CLONE] URL: https://github.com/tesslate/next-js-15.git"
echo "[CLONE] Branch: main"
echo "[CLONE] Target: $TARGET_DIR"
echo "[CLONE] ======================================"

# Clear target directory contents (may be a mount point)
rm -rf "$TARGET_DIR"/* "$TARGET_DIR"/.[!.]* 2>/dev/null || true

# Clone to temp directory
TEMP_CLONE="/tmp/git-clone-$$"
rm -rf "$TEMP_CLONE"
echo "[CLONE] Running git clone..."
git clone --depth 1 --branch main --single-branch \
  https://github.com/tesslate/next-js-15.git "$TEMP_CLONE"

# Verify clone succeeded
if [ ! -f "$TEMP_CLONE/package.json" ] && \
   [ ! -f "$TEMP_CLONE/requirements.txt" ] && \
   [ ! -f "$TEMP_CLONE/go.mod" ]; then
    echo "[CLONE] ERROR: Clone failed - no package manifest found"
    ls -la "$TEMP_CLONE/" 2>/dev/null || true
    exit 1
fi

echo "[CLONE] Clone successful, copying files..."

# Remove .git folder (save space)
rm -rf "$TEMP_CLONE/.git"

# Copy all files including hidden ones
cp -a "$TEMP_CLONE"/. "$TARGET_DIR"/

# Fix ownership (file-manager runs as root, dev containers as node)
chown -R node:node "$TARGET_DIR" 2>/dev/null || true

# Cleanup
rm -rf "$TEMP_CLONE"

# Verify files were copied
if [ ! -f "$TARGET_DIR/package.json" ] && \
   [ ! -f "$TARGET_DIR/requirements.txt" ] && \
   [ ! -f "$TARGET_DIR/go.mod" ]; then
    echo "[CLONE] ERROR: Copy failed - target directory is empty"
    exit 1
fi

echo "[CLONE] Files copied successfully"
echo "[CLONE] ======================================"
echo "[CLONE] ✅ Clone complete"
ls -la "$TARGET_DIR/" | head -20
echo "[CLONE] ======================================"
```

**Key Points**:

**Shallow Clone**: `--depth 1` only fetches latest commit (faster, saves space).

**Temp Directory**: Clones to temp first, then copies (safer than cloning directly to target).

**Validation**: Checks for `package.json`, `requirements.txt`, or `go.mod` to ensure clone succeeded.

**Ownership**: Changes files to `node:node` (1000:1000) for dev container compatibility.

**No Dependencies**: `install_deps=False` means dependencies are NOT installed during file initialization. They're installed by the dev container's startup command (`npm install && npm run dev`). This keeps file initialization fast and non-blocking.

## S3 Scripts (Deprecated)

**Functions**: `generate_s3_upload_script()`, `generate_s3_download_script()`

**Status**: These are still in the codebase but are NOT used by the new architecture. S3 operations are now performed securely by the backend pod using boto3 + file streaming.

**Old approach** (insecure):
1. Init container with AWS credentials as env vars
2. Init container runs `aws s3 cp` directly
3. ❌ Problem: AWS credentials exposed to user pods

**New approach** (secure):
1. Backend pod zips project via file-manager (`kubectl exec`)
2. Backend pod copies zip from pod to backend temp dir (k8s stream API)
3. Backend pod uploads to S3 using boto3 (credentials in backend only)
4. ✅ AWS credentials never leave backend pod

## Usage Examples

### Complete Project Setup

```python
from orchestrator.app.services.orchestration.kubernetes.helpers import *
from orchestrator.app.services.orchestration.kubernetes.client import get_k8s_client

k8s_client = get_k8s_client()
namespace = f"proj-{project_id}"

# 1. Create PVC
pvc = create_pvc_manifest(namespace, project_id, user_id, "tesslate-block-storage", "5Gi")
await k8s_client.create_pvc(pvc, namespace)

# 2. Create file-manager
file_mgr = create_file_manager_deployment(
    namespace, project_id, user_id, "tesslate-devserver:latest"
)
await k8s_client.create_deployment(file_mgr, namespace)

# 3. Create NetworkPolicy
policy = create_network_policy_manifest(namespace, project_id)
await k8s_client.apply_network_policy(policy, namespace)
```

### Start Dev Container

```python
# 1. Create deployment
deployment = create_container_deployment(
    namespace=namespace,
    project_id=project_id,
    user_id=user_id,
    container_id=container_id,
    container_directory="frontend",
    image="tesslate-devserver:latest",
    port=3000,
    startup_command="npm run dev",
    enable_pod_affinity=True
)
await k8s_client.create_deployment(deployment, namespace)

# 2. Create service
service = create_service_manifest(
    namespace, project_id, container_id, "frontend", 3000
)
await k8s_client.create_service(service, namespace)

# 3. Create ingress
ingress = create_ingress_manifest(
    namespace, project_id, container_id, "frontend",
    "my-app-abc123", 3000, "your-domain.com", "nginx", "tesslate-wildcard-tls"
)
await k8s_client.create_ingress(ingress, namespace)
```

### Initialize Container Files

```python
# Generate git clone script
script = generate_git_clone_script(
    git_url="https://github.com/tesslate/next-js-15.git",
    branch="main",
    target_dir="/app/frontend",
    install_deps=False
)

# Execute in file-manager pod
pod_name = await k8s_client.get_file_manager_pod(namespace)
await asyncio.to_thread(
    k8s_client._exec_in_pod,
    pod_name, namespace, "file-manager",
    ["/bin/sh", "-c", script],
    timeout=60
)
```

## Testing

### Unit Tests

Test manifest generation:

```python
from orchestrator.app.services.orchestration.kubernetes.helpers import *

def test_pvc_manifest():
    pvc = create_pvc_manifest(
        namespace="test-ns",
        project_id=UUID("d4f6e8a2-..."),
        user_id=UUID("123e4567-..."),
        storage_class="standard",
        size="1Gi"
    )

    assert pvc.metadata.name == "project-storage"
    assert pvc.spec.storage_class_name == "standard"
    assert pvc.spec.resources.requests["storage"] == "1Gi"
```

### Integration Tests

Test with actual Kubernetes cluster:

```python
async def test_deployment_creation():
    k8s_client = get_k8s_client()
    namespace = "test-proj-123"

    # Create namespace
    await k8s_client.create_namespace_if_not_exists(namespace, "proj-123", user_id)

    # Create file-manager
    deployment = create_file_manager_deployment(namespace, project_id, user_id, "alpine:latest")
    await k8s_client.create_deployment(deployment, namespace)

    # Wait and verify
    await k8s_client.wait_for_deployment_ready("file-manager", namespace)
    pod_name = await k8s_client.get_file_manager_pod(namespace)
    assert pod_name is not None

    # Cleanup
    await k8s_client.delete_namespace(namespace)
```

## Debugging

### View Generated Manifests

```python
import yaml

deployment = create_file_manager_deployment(...)
print(yaml.dump(k8s_client.api_client.sanitize_for_serialization(deployment)))
```

### Apply Manually

```bash
# Save manifest to file
python -c "
from orchestrator.app.services.orchestration.kubernetes.helpers import *
import yaml
from kubernetes import client

deployment = create_file_manager_deployment(...)
manifest = client.ApiClient().sanitize_for_serialization(deployment)
print(yaml.dump(manifest))
" > deployment.yaml

# Apply with kubectl
kubectl apply -f deployment.yaml
```

## Next Steps

- See [kubernetes-client.md](./kubernetes-client.md) for how manifests are applied
- See [kubernetes-mode.md](./kubernetes-mode.md) for orchestrator usage
- Review Kubernetes documentation for manifest specifications
