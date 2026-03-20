# CLAUDE.md - Container Orchestration Context

## Purpose

You are working on the container orchestration layer for Tesslate Studio. This system manages the lifecycle of user project containers across two deployment modes: Docker Compose (local development) and Kubernetes (production).

## When to Load This Context

Load this context when:
- Modifying container lifecycle behavior (start/stop/restart)
- Adding support for new deployment modes
- Implementing file operations for agent tools
- Debugging container startup or networking issues
- Working on hibernation/cleanup logic
- Implementing new orchestrator methods

## Key Files

### Core Interfaces & Factory

**`orchestrator/app/services/orchestration/base.py`**
- Abstract base class defining the orchestrator interface
- ALL orchestrators must implement these methods
- Ensures feature parity between Docker and Kubernetes modes
- Key methods: `start_project()`, `read_file()`, `execute_command()`, `cleanup_idle_environments()`

**`orchestrator/app/services/orchestration/factory.py`**
- Factory pattern for creating orchestrators
- `get_orchestrator()` - Main entry point, returns correct orchestrator based on config
- Singleton caching to avoid repeated initialization
- Convenience functions: `is_docker_mode()`, `is_kubernetes_mode()`

**`orchestrator/app/services/orchestration/deployment_mode.py`**
- Type-safe enum for deployment modes
- Properties: `.is_docker`, `.is_kubernetes`
- Conversion: `DeploymentMode.from_string("kubernetes")`

### Docker Orchestrator

**`orchestrator/app/services/orchestration/docker.py`**
- Docker Compose-based orchestration for local development
- Direct filesystem access via shared volume (`/projects`)
- Traefik integration for routing (`*.localhost`)
- Dynamic `docker-compose.yml` generation
- `_resolve_service_name()` for proper Docker Compose service name resolution (handles both full container names with slug prefix and display names)
- Key patterns:
  - Volume subpath isolation (requires Docker Compose v2.23.0+)
  - Direct Traefik routing (single Traefik → container)
  - Two-tier cleanup (pause → delete)

### Kubernetes Orchestrator

**`orchestrator/app/services/orchestration/kubernetes_orchestrator.py`**
- Kubernetes-based orchestration for production
- Namespace per project pattern (`proj-{uuid}`)
- File-manager pod (always running) + dev container pods (on-demand)
- S3 Sandwich pattern for hibernation
- Key patterns:
  - File lifecycle SEPARATE from container lifecycle
  - Pod affinity for shared RWO storage
  - NetworkPolicy for isolation
  - Secure S3 streaming (credentials never in user pods)

**`orchestrator/app/services/orchestration/kubernetes/client.py`**
- Wrapper around Kubernetes Python client
- Handles namespace, deployment, service, ingress CRUD
- Pod exec for file operations and shell commands
- File streaming to/from pods (for S3 sandwich)

**`orchestrator/app/services/orchestration/kubernetes/helpers.py`**
- Manifest generation functions
- `create_pvc_manifest()` - Project storage
- `create_file_manager_deployment()` - Always-running file pod
- `create_container_deployment()` - Dev server deployment
- `create_service_manifest()`, `create_ingress_manifest()` - Networking
- `generate_git_clone_script()` - Template initialization

## Related Contexts

### Services Layer
- **`docs/orchestrator/services/`** - Service definitions (Postgres, Redis, etc.)
- **`docs/orchestrator/services/base-config-parser.md`** - TESSLATE.md parsing

### Infrastructure
- **`docs/infrastructure/kubernetes/`** - K8s cluster setup, ingress, cert-manager
- **`docs/infrastructure/docker/`** - Local Docker setup, Traefik configuration

### API Layer
- **`orchestrator/app/routers/projects.py`** - Project API endpoints that use orchestrator
- **`orchestrator/app/routers/chat.py`** - AI agent integration (uses file operations)

## Quick Reference: Orchestrator Methods

### Project Lifecycle

```python
# Start all containers
result = await orchestrator.start_project(
    project, containers, connections, user_id, db
)

# Stop all containers
await orchestrator.stop_project(project_slug, project_id, user_id)

# Restart all containers
result = await orchestrator.restart_project(
    project, containers, connections, user_id, db
)

# Get status
status = await orchestrator.get_project_status(project_slug, project_id)
```

### Individual Container Management

```python
# Start single container
result = await orchestrator.start_container(
    project, container, all_containers, connections, user_id, db
)

# Stop single container
await orchestrator.stop_container(
    project_slug, project_id, container_name, user_id
)

# Get container status
status = await orchestrator.get_container_status(
    project_slug, project_id, container_name, user_id
)
```

### File Operations (for Agent Tools)

```python
# Read file
content = await orchestrator.read_file(
    user_id, project_id, container_name, file_path,
    project_slug=None, subdir=None,
    volume_id=None, cache_node=None,  # K8s volume routing hints (ignored by Docker)
)

# Write file
success = await orchestrator.write_file(
    user_id, project_id, container_name, file_path, content,
    project_slug=None, subdir=None,
    volume_id=None, cache_node=None,  # K8s volume routing hints (ignored by Docker)
)

# Delete file
success = await orchestrator.delete_file(
    user_id, project_id, container_name, file_path
)

# List files
files = await orchestrator.list_files(
    user_id, project_id, container_name, directory="."
)
# Note: File listings include empty directory placeholders.
# These have file_path ending in "/" and empty content.
# Both Docker (get_files_with_content) and K8s (read_files_recursive)
# modes emit these entries so the frontend can render empty dirs.
```

### Shell Operations (for Agent Tools)

```python
# Execute command
output = await orchestrator.execute_command(
    user_id, project_id, container_name,
    command=["npm", "install"],
    timeout=120,
    working_dir=None
)

# Check if container is ready
status = await orchestrator.is_container_ready(
    user_id, project_id, container_name
)
```

### Activity Tracking & Cleanup

```python
# Track activity (updates last_activity timestamp)
orchestrator.track_activity(user_id, project_id, container_name=None)

# Cleanup idle environments (called by cronjob)
cleaned = await orchestrator.cleanup_idle_environments(
    idle_timeout_minutes=30
)
```

## Architecture Patterns

### 1. Separation of Lifecycles (Kubernetes)

```
FILE LIFECYCLE:
  1. User adds container to graph
  2. File-manager pod runs `git clone` to /app/{container-dir}/
  3. Files persist on PVC

CONTAINER LIFECYCLE:
  1. User clicks "Start"
  2. Dev container deployment created
  3. Mounts existing PVC (files already present)
  4. No init containers needed!

S3 LIFECYCLE (Hibernation):
  1. User leaves project or idle timeout reached
  2. Backend zips /app/ via file-manager pod
  3. Backend uploads to S3 (credentials in backend only)
  4. Delete namespace (including PVC)
  5. On return: Reverse process (download, unzip, start)
```

### 2. Factory Pattern

All code uses the factory:

```python
from orchestrator.app.services.orchestration import get_orchestrator

orchestrator = get_orchestrator()  # Returns Docker or K8s based on config
await orchestrator.start_project(...)
```

Never do:
```python
# BAD: Direct instantiation
from orchestrator.app.services.orchestration.docker import DockerOrchestrator
orchestrator = DockerOrchestrator()  # Bypasses factory, breaks caching
```

### 3. BaseOrchestrator Interface

When adding a new method to the interface:

1. Add abstract method to `base.py`
2. Implement in `docker.py`
3. Implement in `kubernetes_orchestrator.py`
4. Update this documentation

Example:
```python
# base.py
@abstractmethod
async def my_new_method(self, arg1: str) -> Dict[str, Any]:
    """Description of what this does."""
    pass

# docker.py
async def my_new_method(self, arg1: str) -> Dict[str, Any]:
    # Docker implementation
    pass

# kubernetes_orchestrator.py
async def my_new_method(self, arg1: str) -> Dict[str, Any]:
    # K8s implementation
    pass
```

### 4. Kubernetes Client Wrapper

The `KubernetesClient` class wraps the Kubernetes Python client to:
- Provide async/await interface
- Handle errors consistently
- Prevent WebSocket concurrency bugs (uses fresh clients for stream operations)
- Simplify common operations

Always use the wrapper, not the raw Kubernetes client:

```python
# GOOD
from orchestrator.app.services.orchestration.kubernetes.client import get_k8s_client

k8s_client = get_k8s_client()
await k8s_client.create_deployment(deployment, namespace)

# BAD
from kubernetes import client
apps_v1 = client.AppsV1Api()
apps_v1.create_namespaced_deployment(...)  # Doesn't handle errors, not async
```

## Common Patterns

### Getting the Orchestrator

```python
from orchestrator.app.services.orchestration import get_orchestrator

orchestrator = get_orchestrator()
```

### Checking Deployment Mode

```python
from orchestrator.app.services.orchestration import is_kubernetes_mode, is_docker_mode

if is_kubernetes_mode():
    # K8s-specific logic
    pass

if is_docker_mode():
    # Docker-specific logic
    pass
```

### Error Handling

Both orchestrators raise exceptions on failure:

```python
try:
    await orchestrator.start_project(...)
except RuntimeError as e:
    logger.error(f"Failed to start project: {e}")
    # Handle error
```

### Multi-Container Projects

For projects with multiple containers (e.g., frontend + backend):

```python
# Files are in subdirectories
await orchestrator.read_file(
    user_id, project_id,
    container_name="frontend",
    file_path="src/App.tsx",
    subdir="frontend"  # Important for multi-container!
)
```

## Port Resolution

Use `container.effective_port` everywhere you need "the port the dev server listens on." Never write ad-hoc fallback chains like `container.internal_port or container.port or 3000`.

Resolution order (defined in `Container.effective_port` property on the model):
1. `internal_port` — set during project creation from TESSLATE.md / framework detection
2. `port` — the exposed/mapped port (sometimes the same)
3. `3000` — last-resort default

## Container Startup Command Priority Chain

Both Docker and Kubernetes orchestrators determine the startup command and port using the same priority chain:

1. **DB `startup_command`** (`Container.startup_command`): Highest priority. Set by setup-config or project creation.
2. **`.tesslate/config.json`**: Read from PVC via file-manager pod (K8s) or filesystem (Docker). Fallback for older projects.
3. **TESSLATE.md**: Legacy markdown config parsed for port and start_command.
4. **Generic fallback**: `npm install && npm run dev` with port from `container.effective_port`.

## Agent-Assisted Container Startup

Community bases (external repos without `TESSLATE.md`) often fail the default `npm install && npm run dev` startup — Django, Go, Rust, Laravel, etc. won't start on port 3000 with that command.

**How it works**:
1. K8s startup/liveness probes are exec-based (`tmux has-session -t main`), not HTTP. Container stays alive even if the dev server never starts.
2. Docker doesn't kill containers on health check failure (already fine).
3. Frontend health check times out after ~120s → shows "Container needs setup" UI with an "Ask Agent to start it" button.
4. Button prefills the chat with: "Use the running tmux process to get this up and running. The port for the preview url is {port}."
5. Agent reads the project files, figures out the correct startup command, and runs it in the tmux session on the correct port.

**Key files**:
- `kubernetes/helpers.py` — exec-based startup/liveness probes
- `app/src/hooks/useContainerStartup.ts` — `HEALTH_CHECK_TIMEOUT:` error prefix
- `app/src/components/ContainerLoadingOverlay.tsx` — "Ask Agent" UI for health check timeouts
- `app/src/pages/Project.tsx` — `prefillChatMessage` state wiring
- `app/src/components/chat/ChatInput.tsx` — `prefillMessage` prop to set input value

## Critical Implementation Details

### Docker Mode

1. **Volume Subpath Isolation**:
   - Uses Docker Compose v2.23.0+ `volume.subpath` feature
   - Each project mounted at `/projects/{slug}`
   - Requires `tesslate-projects-data` volume to exist

2. **Traefik Routing**:
   - Labels in `docker-compose.yml` configure Traefik
   - URL format: `{project-slug}-{container-name}.localhost`
   - Traefik must be connected to project network

3. **File Operations**:
   - Direct filesystem access (orchestrator reads `/projects/{slug}/`)
   - Fast and simple (no pod exec needed)
   - `get_files_with_content()` includes empty directory placeholders (path ending in `/`, empty content) detected during `os.walk` when a directory has no non-excluded files and no remaining subdirectories

### Kubernetes Mode

1. **Namespace Per Project**:
   - Namespace name: `proj-{project-uuid}`
   - All resources scoped to namespace (easy cleanup)
   - NetworkPolicy for isolation

2. **File-Manager Pod**:
   - Always running while project is open
   - Handles file operations when dev container not running
   - Executes `git clone` when container added to graph

3. **Pod Affinity**:
   - Multi-container projects must run on same node (for RWO PVC)
   - Configured via `podAffinity` in deployment spec
   - Topology key: `kubernetes.io/hostname`

4. **S3 Sandwich Pattern**:
   - Backend pod zips project → streams to backend temp → uploads to S3
   - Reverse for restoration
   - AWS credentials NEVER exposed to user namespaces
   - This is a security requirement!

5. **WebSocket Bug Workaround**:
   - Kubernetes Python client `stream()` temporarily patches API client
   - If shared client is used, concurrent calls fail with "WebSocketBadStatusException"
   - Solution: `_get_stream_client()` creates fresh client for each stream operation

## Testing Approach

### Unit Tests

Mock the orchestrator for API endpoint tests:

```python
from unittest.mock import AsyncMock, patch

@patch('orchestrator.app.routers.projects.get_orchestrator')
async def test_start_project(mock_get_orchestrator):
    mock_orchestrator = AsyncMock()
    mock_orchestrator.start_project.return_value = {"status": "running"}
    mock_get_orchestrator.return_value = mock_orchestrator

    # Test API endpoint
    response = await client.post("/api/projects/123/start")
    assert response.status_code == 200
```

### Integration Tests

Test orchestrator directly:

```python
from orchestrator.app.services.orchestration import get_orchestrator

async def test_orchestrator_lifecycle():
    orchestrator = get_orchestrator()

    # Start project
    result = await orchestrator.start_project(project, containers, ...)
    assert result["status"] == "running"

    # Verify files exist
    content = await orchestrator.read_file(...)
    assert content is not None

    # Stop project
    await orchestrator.stop_project(project_slug, project_id, user_id)
```

## Debugging Tips

### Docker Mode

```bash
# View generated compose file
cat docker-compose-projects/my-project-abc123.yml

# Check container status
docker ps | grep my-project

# View logs
docker logs my-project-abc123-frontend

# Check networks
docker network ls | grep tesslate

# Inspect project files
ls /projects/my-project-abc123/
```

### Kubernetes Mode

```bash
# Get namespace for project
NAMESPACE=proj-$(python -c "print('project-uuid-here')")

# Check all resources
kubectl get all -n $NAMESPACE

# Check file-manager logs
kubectl logs -n $NAMESPACE deployment/file-manager -c file-manager

# Exec into file-manager
kubectl exec -n $NAMESPACE deployment/file-manager -c file-manager -- ls -la /app

# Check dev container logs
kubectl logs -n $NAMESPACE deployment/dev-frontend -c dev-server

# Check ingress configuration
kubectl get ingress -n $NAMESPACE -o yaml
```

## Configuration Reference

Key environment variables (see `orchestrator/app/config.py`):

```bash
# Mode selection
DEPLOYMENT_MODE=docker|kubernetes

# Docker settings
USE_DOCKER_VOLUMES=true

# Kubernetes settings
K8S_DEVSERVER_IMAGE=tesslate-devserver:latest
K8S_STORAGE_CLASS=tesslate-block-storage
K8S_PVC_SIZE=5Gi
K8S_NAMESPACE_PER_PROJECT=true
K8S_ENABLE_POD_AFFINITY=true

# S3 configuration
K8S_USE_S3_STORAGE=true
S3_BUCKET_NAME=tesslate-project-storage-prod
S3_ENDPOINT_URL=https://s3.us-east-1.amazonaws.com

# Hibernation
K8S_HIBERNATION_IDLE_MINUTES=30
```

## Next Steps

After understanding orchestration, explore:
- **Agent Tools** - How AI uses file operations (`orchestrator/app/agent/tools/`)
- **Base Config Parser** - TESSLATE.md parsing for container startup
- **Service Definitions** - Postgres, Redis, etc. container definitions
- **Infrastructure** - Cluster setup, networking, storage
