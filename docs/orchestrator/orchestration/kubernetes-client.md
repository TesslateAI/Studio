# Kubernetes Client Wrapper

**File**: `orchestrator/app/services/orchestration/kubernetes/client.py`

The `KubernetesClient` class is a wrapper around the official Kubernetes Python client that provides:
- Async/await interface for all operations
- Consistent error handling
- Simplified common operations (namespace, deployment, service, ingress management)
- Pod exec for file operations and shell commands
- Secure file streaming to/from pods (for S3 sandwich pattern)
- WebSocket concurrency bug workaround

## Purpose

The raw Kubernetes Python client is:
- Synchronous (blocking)
- Verbose (requires many lines for simple operations)
- Error-prone (inconsistent error handling)
- Has a WebSocket concurrency bug

This wrapper provides a clean async interface and handles edge cases.

## Initialization

### In-Cluster vs Out-of-Cluster

The client auto-detects whether it's running inside a Kubernetes cluster:

```python
def __init__(self):
    try:
        # Try in-cluster config first (for production)
        config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes configuration")
    except config.ConfigException:
        try:
            # Fall back to kubeconfig (for development)
            config.load_kube_config()
            logger.info("Loaded kubeconfig for development")
        except config.ConfigException as e:
            raise RuntimeError("Cannot load Kubernetes configuration") from e

    # Initialize API clients
    self.apps_v1 = client.AppsV1Api()
    self.core_v1 = client.CoreV1Api()
    self.networking_v1 = client.NetworkingV1Api()
```

**In-cluster** (production):
- Uses service account token at `/var/run/secrets/kubernetes.io/serviceaccount/token`
- API server URL from `KUBERNETES_SERVICE_HOST` environment variable

**Out-of-cluster** (development):
- Reads `~/.kube/config` or `$KUBECONFIG`
- Uses current context

### Singleton Pattern

```python
from orchestrator.app.services.orchestration.kubernetes.client import get_k8s_client

k8s_client = get_k8s_client()  # Returns cached instance
```

## Namespace Operations

### Create Namespace

```python
await k8s_client.create_namespace_if_not_exists(
    namespace="proj-d4f6e8a2-...",
    project_id="d4f6e8a2-...",
    user_id=user_id
)
```

**Implementation**:
- Checks if namespace exists (404 = create it)
- Adds labels: `app=tesslate`, `managed-by=tesslate-backend`, `project-id`, `user-id`

### Check if Namespace Exists

```python
exists = await k8s_client.namespace_exists("proj-d4f6e8a2-...")
```

### Get Project Namespace

```python
namespace = k8s_client.get_project_namespace(project_id)
# Returns: "proj-{project_id}" or shared namespace (based on config)
```

## Deployment Operations

### Create Deployment

```python
await k8s_client.create_deployment(deployment, namespace)
```

**Behavior**:
- If deployment exists (409 conflict), patches it instead
- Uses `asyncio.to_thread()` for async operation

**Example**:
```python
from orchestrator.app.services.orchestration.kubernetes.helpers import create_file_manager_deployment

deployment = create_file_manager_deployment(
    namespace=namespace,
    project_id=project_id,
    user_id=user_id,
    image="tesslate-devserver:latest"
)
await k8s_client.create_deployment(deployment, namespace)
```

### Delete Deployment

```python
await k8s_client.delete_deployment("file-manager", namespace)
```

**Behavior**:
- Ignores 404 (already deleted)
- Cascades to pods (default GC policy)

### Scale Deployment

```python
await k8s_client.scale_deployment(user_id, project_id, replicas=0)
```

**Use case**: Pause project without deleting (save resources)

### Wait for Deployment Ready

```python
await k8s_client.wait_for_deployment_ready(
    deployment_name="file-manager",
    namespace=namespace,
    timeout=120
)
```

**Behavior**:
- Polls deployment status every second
- Waits until `ready_replicas == replicas`
- Raises `RuntimeError` if timeout exceeded

## Service Operations

### Create Service

```python
await k8s_client.create_service(service, namespace)
```

**Behavior**:
- If service exists (409), patches it
- ClusterIP services (internal only)

**Example**:
```python
from orchestrator.app.services.orchestration.kubernetes.helpers import create_service_manifest

service = create_service_manifest(
    namespace=namespace,
    project_id=project_id,
    container_id=container_id,
    container_directory="frontend",
    port=3000
)
await k8s_client.create_service(service, namespace)
```

### Delete Service

```python
await k8s_client.delete_service("dev-frontend", namespace)
```

## Ingress Operations

### Create Ingress

```python
await k8s_client.create_ingress(ingress, namespace)
```

**Behavior**:
- If ingress exists (409), patches it
- NGINX ingress controller creates routes

**Example**:
```python
from orchestrator.app.services.orchestration.kubernetes.helpers import create_ingress_manifest

ingress = create_ingress_manifest(
    namespace=namespace,
    project_id=project_id,
    container_id=container_id,
    container_directory="frontend",
    project_slug="my-app-abc123",
    port=3000,
    domain="your-domain.com",
    ingress_class="nginx",
    tls_secret="tesslate-wildcard-tls"
)
await k8s_client.create_ingress(ingress, namespace)
```

### Delete Ingress

```python
await k8s_client.delete_ingress("dev-frontend", namespace)
```

## PVC Operations

### Create PVC

```python
await k8s_client.create_pvc(pvc, namespace)
```

**Behavior**:
- PVCs are immutable (cannot update)
- If already exists (409), logs and continues

**Example**:
```python
from orchestrator.app.services.orchestration.kubernetes.helpers import create_pvc_manifest

pvc = create_pvc_manifest(
    namespace=namespace,
    project_id=project_id,
    user_id=user_id,
    storage_class="tesslate-block-storage",
    size="5Gi",
    access_mode="ReadWriteOnce"
)
await k8s_client.create_pvc(pvc, namespace)
```

### Delete PVC

```python
await k8s_client.delete_pvc("project-storage", namespace)
```

**Warning**: Deletes all data! Only use when permanently deleting project.

## NetworkPolicy Operations

### Create/Update NetworkPolicy

```python
await k8s_client.apply_network_policy(network_policy, namespace)
```

**Behavior**:
- Creates if doesn't exist
- Patches if already exists (409)
- Skipped if `K8S_ENABLE_NETWORK_POLICIES=false`

**Example**:
```python
from orchestrator.app.services.orchestration.kubernetes.helpers import create_network_policy_manifest

policy = create_network_policy_manifest(namespace, project_id)
await k8s_client.apply_network_policy(policy, namespace)
```

## Secret Operations

### Copy Wildcard TLS Secret

```python
success = await k8s_client.copy_wildcard_tls_secret(target_namespace)
```

**Use case**: HTTPS ingress needs TLS certificate in project namespace

**Behavior**:
- Reads secret from `tesslate` namespace
- Creates copy in target namespace
- Returns `False` if secret doesn't exist (OK for local dev without TLS)

### Copy S3 Credentials Secret

**DEPRECATED**: S3 credentials are NO LONGER copied to user namespaces for security reasons. All S3 operations are performed by the backend pod.

```python
# DO NOT USE - Security vulnerability
# await k8s_client.copy_s3_credentials_secret(target_namespace)
```

## Pod Operations

### Get Pod for Deployment

```python
pod_name = await k8s_client.get_pod_for_deployment(
    deployment_name="file-manager",
    namespace=namespace
)
```

**Behavior**:
- Finds first running + ready pod for deployment
- Returns `None` if no ready pod found

### Get File-Manager Pod

```python
pod_name = await k8s_client.get_file_manager_pod(namespace)
```

**Behavior**:
- Convenience method for `get_pod_for_deployment("file-manager", ...)`
- Used extensively for file operations

### Execute Command in Pod

**CRITICAL**: Uses fresh API client for stream operations to avoid WebSocket bug.

```python
output = await asyncio.to_thread(
    k8s_client._exec_in_pod,
    pod_name="file-manager-abc123",
    namespace="proj-d4f6e8a2-...",
    container_name="file-manager",
    command=["cat", "/app/package.json"],
    timeout=30
)
```

**WebSocket Bug Workaround**:

The Kubernetes Python client has a concurrency bug where `stream()` temporarily patches the API client's request method to use WebSocket. If the same API client is used for concurrent operations, regular REST calls fail with "WebSocketBadStatusException: Handshake status 200 OK".

**Solution**: `_exec_in_pod()` creates a fresh API client for each stream operation:

```python
def _get_stream_client(self) -> client.CoreV1Api:
    """Create a fresh CoreV1Api client for stream operations."""
    return client.CoreV1Api()

def _exec_in_pod(self, pod_name, namespace, container_name, command, timeout):
    stream_client = self._get_stream_client()  # Fresh client!
    resp = stream(
        stream_client.connect_get_namespaced_pod_exec,
        pod_name,
        namespace,
        container=container_name,
        command=command,
        ...
    )
    return resp
```

This isolates the WebSocket patching and prevents concurrent call failures.

### Copy File from Pod (S3 Sandwich)

```python
success = await k8s_client.copy_file_from_pod(
    pod_name="file-manager-abc123",
    namespace="proj-d4f6e8a2-...",
    container_name="file-manager",
    pod_path="/tmp/project.zip",
    local_path="/tmp/backend-temp/project.zip",
    timeout=300
)
```

**Implementation**:
- Uses `base64` encoding to safely transfer binary data over WebSocket
- Avoids tar streaming issues with the Kubernetes Python client
- Reads base64-encoded file from pod → decodes → writes to local filesystem

**Use case**: Hibernation (dehydration) - copy project zip from pod to backend

### Copy File to Pod (S3 Sandwich)

```python
success = await k8s_client.copy_file_to_pod(
    pod_name="file-manager-abc123",
    namespace="proj-d4f6e8a2-...",
    container_name="file-manager",
    local_path="/tmp/backend-temp/project.zip",
    pod_path="/tmp/project.zip",
    timeout=300
)
```

**Implementation**:
- Creates tar archive in memory
- Streams tar to pod via stdin
- Pod extracts with `tar xf -`

**Use case**: Restoration (hydration) - copy project zip from backend to pod

## File Operations (High-Level)

These methods use `_exec_in_pod()` internally:

### Read File

```python
content = await k8s_client.read_file_from_pod(
    user_id=user_id,
    project_id=project_id,
    file_path="src/App.tsx",
    container_name="frontend",
    subdir="frontend"
)
```

**Implementation**:
1. Get pod for deployment (or file-manager)
2. Build full path: `/app/{subdir}/{file_path}`
3. Check file exists: `test -f {path}`
4. Read content: `cat {path}`

### Write File

```python
success = await k8s_client.write_file_to_pod(
    user_id=user_id,
    project_id=project_id,
    file_path="src/NewComponent.tsx",
    content=code,
    container_name="frontend",
    subdir="frontend"
)
```

**Implementation**:
1. Get pod for deployment (or file-manager)
2. Build full path: `/app/{subdir}/{file_path}`
3. Ensure parent directory exists: `mkdir -p {dir}`
4. Write file using heredoc (handles special characters):
   ```bash
   cat > {path} << 'EOF_MARKER'
   {content}
   EOF_MARKER
   ```

### Delete File

```python
success = await k8s_client.delete_file_from_pod(
    user_id=user_id,
    project_id=project_id,
    file_path="src/OldComponent.tsx",
    container_name="frontend"
)
```

**Implementation**:
```bash
rm -f /app/{subdir}/{file_path}
```

### List Files

```python
files = await k8s_client.list_files_in_pod(
    user_id=user_id,
    project_id=project_id,
    directory="src",
    container_name="frontend"
)
```

**Implementation**:
1. Execute `ls -la {directory}`
2. Parse output into list of dicts:
   ```python
   [
       {"name": "App.tsx", "type": "file", "size": 1234, "permissions": "rw-r--r--"},
       {"name": "components", "type": "directory", ...},
   ]
   ```

## Advanced File Operations

### Glob Files

```python
matches = await k8s_client.glob_files_in_pod(
    user_id=user_id,
    project_id=project_id,
    pattern="*.tsx",
    directory="src",
    container_name="frontend"
)
```

**Implementation**:
```bash
cd /app/{directory} && find . -type f -name '{pattern}'
```

### Grep Files

```python
matches = await k8s_client.grep_in_pod(
    user_id=user_id,
    project_id=project_id,
    pattern="useState",
    directory="src",
    file_pattern="*.tsx",
    case_sensitive=True,
    max_results=100,
    container_name="frontend"
)
```

**Implementation**:
```bash
cd /app/{directory} && grep -rn {case_flag} '{pattern}' --include='{file_pattern}' . | head -n {max_results}
```

**Returns**:
```python
[
    {"file": "src/App.tsx", "line": 5, "content": "const [count, setCount] = useState(0)"},
    ...
]
```

## Shell Execution

### Execute Command in Pod

```python
output = await k8s_client.execute_command_in_pod(
    user_id=user_id,
    project_id=project_id,
    command=["npm", "install", "axios"],
    timeout=120,
    container_name="frontend"
)
```

**Implementation**:
1. Get pod for deployment
2. Check pod is running
3. Execute command: `/bin/sh -c "cd /app && {command}"`
4. Return stdout + stderr

### Check Pod Readiness

```python
status = await k8s_client.check_pod_ready(
    user_id=user_id,
    project_id=project_id,
    check_responsive=True,
    container_name="frontend"
)
```

**Returns**:
```python
{
    "ready": True,
    "phase": "Running",
    "conditions": ["Ready", "ContainersReady"],
    "responsive": True,
    "message": "Pod is ready and responsive",
    "pod_name": "dev-frontend-abc123"
}
```

**Responsiveness check**:
- Executes `echo ready` in pod
- Ensures pod can actually execute commands (not just Kubernetes-ready)

## Helper Methods

### Resource Name Generation

```python
names = k8s_client.generate_resource_names(
    user_id=user_id,
    project_id=project_id,
    project_slug="my-app-abc123",
    container_name="frontend"
)
```

**Returns**:
```python
{
    "namespace": "proj-d4f6e8a2-...",
    "deployment": "dev-976599df-7745b013-frontend",
    "service": "dev-976599df-7745b013-frontend-svc",
    "ingress": "dev-976599df-7745b013-frontend-ing",
    "hostname": "my-app-abc123-frontend.your-domain.com",
    "safe_container_name": "frontend"
}
```

**Purpose**: Consistent naming across all K8s resources.

### Check if Pod is Ready

```python
is_ready = k8s_client.is_pod_ready(pod)
```

**Implementation**:
```python
for condition in pod.status.conditions:
    if condition.type == "Ready" and condition.status == "True":
        return True
return False
```

## Error Handling

All methods handle `ApiException` from the Kubernetes client:

```python
try:
    await k8s_client.create_deployment(deployment, namespace)
except ApiException as e:
    if e.status == 409:
        # Already exists, patch instead
        await k8s_client.patch_deployment(...)
    elif e.status == 404:
        # Not found, ignore or handle
        logger.warning(f"Namespace not found: {namespace}")
    else:
        # Unexpected error, re-raise
        raise
```

**Common status codes**:
- `404`: Not found (resource doesn't exist)
- `409`: Conflict (resource already exists)
- `422`: Unprocessable entity (validation error)
- `403`: Forbidden (RBAC issue)

## Configuration

Environment variables that affect the client:

```bash
# Kubernetes configuration
KUBERNETES_NAMESPACE=tesslate  # Main namespace for backend
K8S_DEFAULT_NAMESPACE=tesslate
K8S_USER_ENVIRONMENTS_NAMESPACE=user-projects  # Legacy (not used with namespace-per-project)

# Namespace strategy
K8S_NAMESPACE_PER_PROJECT=true  # Each project gets own namespace

# Network policies
K8S_ENABLE_NETWORK_POLICIES=true

# TLS
K8S_WILDCARD_TLS_SECRET=tesslate-wildcard-tls

# S3 credentials (deprecated - kept in backend only)
# K8S_S3_CREDENTIALS_SECRET=s3-credentials
```

## Usage Examples

### Complete Project Setup

```python
from orchestrator.app.services.orchestration.kubernetes.client import get_k8s_client
from orchestrator.app.services.orchestration.kubernetes.helpers import *

k8s_client = get_k8s_client()
namespace = f"proj-{project_id}"

# 1. Create namespace
await k8s_client.create_namespace_if_not_exists(namespace, project_id, user_id)

# 2. Create PVC
pvc = create_pvc_manifest(namespace, project_id, user_id, "tesslate-block-storage")
await k8s_client.create_pvc(pvc, namespace)

# 3. Copy TLS secret
await k8s_client.copy_wildcard_tls_secret(namespace)

# 4. Create file-manager
file_mgr = create_file_manager_deployment(namespace, project_id, user_id, "tesslate-devserver:latest")
await k8s_client.create_deployment(file_mgr, namespace)

# 5. Wait for ready
await k8s_client.wait_for_deployment_ready("file-manager", namespace)

# 6. Initialize files via git clone
pod_name = await k8s_client.get_file_manager_pod(namespace)
await asyncio.to_thread(
    k8s_client._exec_in_pod,
    pod_name, namespace, "file-manager",
    ["/bin/sh", "-c", git_clone_script],
    timeout=60
)
```

### Start Dev Container

```python
# 1. Create deployment
deployment = create_container_deployment(
    namespace, project_id, user_id, container_id,
    "frontend", "tesslate-devserver:latest",
    port=3000, startup_command="npm run dev"
)
await k8s_client.create_deployment(deployment, namespace)

# 2. Create service
service = create_service_manifest(namespace, project_id, container_id, "frontend", 3000)
await k8s_client.create_service(service, namespace)

# 3. Create ingress
ingress = create_ingress_manifest(
    namespace, project_id, container_id, "frontend",
    "my-app-abc123", 3000, "your-domain.com", "nginx", "tesslate-wildcard-tls"
)
await k8s_client.create_ingress(ingress, namespace)

# URL: https://my-app-abc123-frontend.your-domain.com
```

## Debugging Tips

### Enable Debug Logging

```python
import logging
logging.getLogger("orchestrator.app.services.orchestration.kubernetes.client").setLevel(logging.DEBUG)
```

### Inspect API Calls

The client logs all operations:
```
[K8S] Created deployment: file-manager
[K8S] ✅ Created PVC: project-storage
[K8S:EXEC] Executing in pod file-manager-abc123: cat /app/package.json
```

### Test Connectivity

```python
# List namespaces (requires cluster-admin or read permissions)
namespaces = await asyncio.to_thread(k8s_client.core_v1.list_namespace)
print(f"Found {len(namespaces.items)} namespaces")
```

## Next Steps

- See [kubernetes-helpers.md](./kubernetes-helpers.md) for manifest generation functions
- See [kubernetes-mode.md](./kubernetes-mode.md) for orchestrator implementation
- Review [base.py](../base.py) for the orchestrator interface
