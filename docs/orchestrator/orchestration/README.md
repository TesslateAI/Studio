# Container Orchestration

The orchestration layer manages the lifecycle of user project containers across two deployment modes: **Docker Compose** for local development and **Kubernetes** for production. This layer provides a consistent interface regardless of deployment environment, allowing the rest of the codebase to remain agnostic to the underlying infrastructure.

## Overview

User projects in OpenSail run in isolated containerized environments. Each project can have multiple containers (frontend, backend, database) that communicate over a private network. The orchestration layer handles:

- **Container lifecycle**: Starting, stopping, and restarting containers
- **File operations**: Reading/writing project files for the AI agent
- **Shell execution**: Running commands inside containers (npm install, git, etc.)
- **Resource management**: Networking, storage, and inter-container communication
- **Cleanup**: Hibernating or deleting idle projects to save resources

## Architecture

The orchestration system uses a **factory pattern** with a common base interface:

```
┌─────────────────────────────────────────────────────────┐
│                  BaseOrchestrator                       │
│            (Abstract Interface)                         │
│  - start_project() / stop_project()                     │
│  - read_file() / write_file()                           │
│  - execute_command()                                    │
│  - cleanup_idle_environments()                          │
└─────────────────────────────────────────────────────────┘
                    ▲                   ▲
                    │                   │
        ┌───────────┴───────┐  ┌────────┴─────────────┐
        │                   │  │                      │
   DockerOrchestrator       │  │   KubernetesOrchestrator
   (docker-mode.md)         │  │   (kubernetes-mode.md)
                            │  │
                            │  │
                    OrchestratorFactory
                         (factory.py)
                              │
                    ┌─────────┴─────────┐
                    │ config.py:        │
                    │ DEPLOYMENT_MODE   │
                    └───────────────────┘
```

The factory reads `config.DEPLOYMENT_MODE` (set via environment variable) and returns the appropriate orchestrator. All API endpoints use `get_orchestrator()` to obtain the correct implementation.

## Two Deployment Modes

### Docker Mode (Local Development)

**Location**: `orchestrator/app/services/orchestration/docker.py`

Docker mode uses **Docker Compose** to manage user projects. Each project gets:
- A dedicated Docker network for isolation
- Services defined in a dynamically-generated `docker-compose.yml`
- **Traefik** routing for `*.localhost` URLs
- Direct filesystem access via shared volume (`/projects`)

**Key characteristics**:
- Fast iteration (no cluster overhead)
- Simple file operations (orchestrator has direct filesystem access)
- Traefik auto-discovery via labels
- Two-tier cleanup: pause → delete

**URL pattern**: `http://my-project-frontend.localhost`

See [docker-mode.md](./docker-mode.md) for details.

### Kubernetes Mode (Production)

**Location**: `orchestrator/app/services/orchestration/kubernetes_orchestrator.py`

Kubernetes mode creates a **namespace per project** with:
- PersistentVolumeClaim (PVC) for file storage
- **File-manager pod** (always running for file operations)
- **Dev container pods** (started on-demand when user clicks "Start")
- NetworkPolicy for project isolation
- NGINX Ingress for HTTPS routing

**Key characteristics**:
- Scalable (handles thousands of projects)
- **S3 Sandwich pattern**: Hibernate projects to S3 when idle
- Pod affinity for shared storage (RWO volumes)
- Secure: S3 credentials never exposed to user pods

**URL pattern**: `https://my-project-frontend.your-domain.com`

See [kubernetes-mode.md](./kubernetes-mode.md) for details.

## Key Design Principles

### 1. Separation of Concerns

The orchestration layer separates three distinct lifecycles:

```
FILE LIFECYCLE      →  Template setup, git clone
  ↓
CONTAINER LIFECYCLE →  Start/stop dev servers
  ↓
S3 LIFECYCLE        →  Hibernation/restoration (K8s only)
```

**Critical insight**: Files are populated **before** containers start. In Kubernetes, the file-manager pod runs `git clone` when a container is added to the architecture graph. When the user clicks "Start", the dev container launches with files already present—no init containers needed.

### 2. BaseOrchestrator Interface

All orchestrators implement the same interface (`base.py`), ensuring feature parity:

```python
class BaseOrchestrator(ABC):
    @abstractmethod
    async def start_project(self, project, containers, ...):
        """Start all containers for a project."""

    @abstractmethod
    async def read_file(self, user_id, project_id, file_path, ...):
        """Read a file from project storage."""

    @abstractmethod
    async def execute_command(self, user_id, project_id, command, ...):
        """Execute a command in a container."""
```

API endpoints use this interface without caring about the underlying mode:

```python
from orchestrator.app.services.orchestration import get_orchestrator

orchestrator = get_orchestrator()  # Factory returns Docker or K8s
await orchestrator.start_project(project, containers, ...)
```

### 3. Security Model

**Docker mode**:
- Shared volume with subpath isolation (requires Docker Compose v2.23.0+)
- Container user runs as `1000:1000` (non-root)
- Internal services blocked via `/etc/hosts` overrides

**Kubernetes mode**:
- Namespace isolation with NetworkPolicy
- S3 credentials **never** exposed to user namespaces
- Backend pod handles S3 uploads/downloads via secure streaming
- RBAC limits what pods can access

### 4. Activity Tracking & Cleanup

**Docker mode**:
- In-memory activity tracker (single orchestrator instance)
- Two-tier cleanup: scale to 0 → delete after longer timeout

**Kubernetes mode**:
- Database-based tracking (`Project.last_activity`)
- Supports horizontal scaling (multiple backend replicas)
- Hibernation: Save to S3 → delete namespace → restore on return

## Key Components

### Factory Pattern (`factory.py`)

Centralizes orchestrator creation and caching:

```python
from orchestrator.app.services.orchestration import get_orchestrator

# Get orchestrator for current mode
orchestrator = get_orchestrator()

# Check deployment mode
from orchestrator.app.services.orchestration import is_kubernetes_mode
if is_kubernetes_mode():
    # K8s-specific logic
```

### Deployment Mode Enum (`deployment_mode.py`)

Type-safe deployment mode handling:

```python
from orchestrator.app.services.orchestration import DeploymentMode

mode = DeploymentMode.from_string("kubernetes")
if mode.is_kubernetes:
    # Kubernetes-specific code
```

### Kubernetes Client (`kubernetes/client.py`)

Wrapper around the Kubernetes Python client that provides:
- Namespace management
- Deployment/Service/Ingress CRUD
- Pod exec (file operations, shell commands)
- File streaming to/from pods (for S3 sandwich)

See [kubernetes-client.md](./kubernetes-client.md) for details.

### Kubernetes Helpers (`kubernetes/helpers.py`)

Manifest generation functions:
- `create_pvc_manifest()` - Project storage
- `create_service_pvc_manifest()` - Service-specific PVC storage
- `create_file_manager_deployment()` - Always-running file pod
- `create_container_deployment()` - Dev server deployment
- `create_service_container_deployment()` - Service container deployment
- `create_service_manifest()` / `create_ingress_manifest()` - Networking
- `generate_git_clone_script()` - Template initialization

See [kubernetes-helpers.md](./kubernetes-helpers.md) for details.

### Container Startup Command Priority

Both Docker and Kubernetes orchestrators use the same priority chain for determining the startup command:

1. **DB `startup_command`** (`Container.startup_command`) - Set by setup-config or project creation
2. **`.tesslate/config.json`** - Read from project files
3. **TESSLATE.md** - Legacy markdown config
4. **Generic fallback** - `npm install && npm run dev`

## Common Operations

### Starting a Project

```python
orchestrator = get_orchestrator()

result = await orchestrator.start_project(
    project=project,
    containers=containers,
    connections=connections,
    user_id=user_id,
    db=db
)

# Result contains URLs for each container
print(result["containers"])
# {"frontend": "http://my-proj-frontend.localhost", ...}
```

### Reading/Writing Files (for AI Agent)

```python
# Read file
content = await orchestrator.read_file(
    user_id=user_id,
    project_id=project_id,
    container_name="frontend",
    file_path="src/App.tsx"
)

# Write file
success = await orchestrator.write_file(
    user_id=user_id,
    project_id=project_id,
    container_name="frontend",
    file_path="src/NewComponent.tsx",
    content=new_code
)
```

### Executing Commands

```python
# Run npm install
output = await orchestrator.execute_command(
    user_id=user_id,
    project_id=project_id,
    container_name="frontend",
    command=["npm", "install"],
    timeout=300
)
```

### Cleanup (Hibernation)

```python
# Called periodically by cronjob
cleaned = await orchestrator.cleanup_idle_environments(
    idle_timeout_minutes=30
)

# Returns list of hibernated project IDs
```

## File Structure

```
orchestrator/app/services/orchestration/
├── base.py                       # Abstract base interface
├── deployment_mode.py            # Enum for deployment modes
├── factory.py                    # Orchestrator factory
├── docker.py                     # Docker Compose orchestrator
├── kubernetes_orchestrator.py    # Kubernetes orchestrator
└── kubernetes/
    ├── client.py                 # K8s API wrapper
    └── helpers.py                # Manifest generation
```

## Configuration

Orchestrator behavior is controlled via environment variables (see `orchestrator/app/config.py`):

### Common Settings

```bash
DEPLOYMENT_MODE=docker|kubernetes  # Choose orchestrator
APP_DOMAIN=localhost               # Base domain for URLs
```

### Docker-Specific Settings

```bash
USE_DOCKER_VOLUMES=true            # Use volumes vs bind mounts
```

### Kubernetes-Specific Settings

```bash
# Image configuration
K8S_DEVSERVER_IMAGE=tesslate-devserver:latest
K8S_IMAGE_PULL_POLICY=IfNotPresent
K8S_IMAGE_PULL_SECRET=               # Registry secret (empty for local images)

# Storage configuration
K8S_STORAGE_CLASS=tesslate-block-storage
K8S_PVC_SIZE=5Gi
K8S_PVC_ACCESS_MODE=ReadWriteOnce

# S3 Sandwich pattern
K8S_USE_S3_STORAGE=true
S3_BUCKET_NAME=tesslate-project-storage-prod
S3_ENDPOINT_URL=https://nyc3.digitaloceanspaces.com

# Namespace configuration
K8S_NAMESPACE_PER_PROJECT=true
K8S_ENABLE_POD_AFFINITY=true       # Keep multi-container projects on same node
K8S_ENABLE_NETWORK_POLICIES=true

# TLS
K8S_WILDCARD_TLS_SECRET=tesslate-wildcard-tls

# Hibernation
K8S_HIBERNATION_IDLE_MINUTES=30
```

## Debugging

### Docker Mode

```bash
# View generated compose file
cat docker-compose-projects/my-project-abc123.yml

# Check container logs
docker logs my-project-abc123-frontend

# List networks
docker network ls | grep tesslate

# List project files
ls /projects/my-project-abc123/
```

### Kubernetes Mode

```bash
# Get project namespace
PROJECT_ID=<uuid>
NAMESPACE=proj-$PROJECT_ID

# Check pods
kubectl get pods -n $NAMESPACE

# Check file-manager logs
kubectl logs -n $NAMESPACE deployment/file-manager

# Check dev container logs
kubectl logs -n $NAMESPACE deployment/dev-frontend

# Exec into file-manager
kubectl exec -n $NAMESPACE deployment/file-manager -c file-manager -- ls -la /app

# Check ingress
kubectl get ingress -n $NAMESPACE
```

## Troubleshooting

### Container Won't Start

**Docker**: Check `docker-compose.yml` syntax and logs
**Kubernetes**: Check pod events (`kubectl describe pod`)

### Files Not Found

**Docker**: Verify `/projects/{slug}/` directory exists and has correct permissions
**Kubernetes**: Check file-manager pod logs, verify git clone succeeded

### Networking Issues

**Docker**: Ensure Traefik is connected to project network
**Kubernetes**: Check NetworkPolicy, Ingress configuration, and DNS

### S3 Hibernation Failures (K8s)

- Check S3 credentials in backend pod (not user namespace)
- Verify backend can stream files to/from pods
- Check S3 bucket exists and backend has write permissions

## Next Steps

- **[Docker Mode Details](./docker-mode.md)** - Docker Compose orchestration
- **[Kubernetes Mode Details](./kubernetes-mode.md)** - Kubernetes orchestration
- **[Kubernetes Client](./kubernetes-client.md)** - K8s API wrapper
- **[Kubernetes Helpers](./kubernetes-helpers.md)** - Manifest generation
- **[CLAUDE.md](./CLAUDE.md)** - Agent context for orchestration development
