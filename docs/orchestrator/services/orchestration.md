# Container Orchestration Services

OpenSail uses a unified orchestration layer that abstracts Docker Compose, Kubernetes, and local-subprocess deployments behind a common interface. The same codebase runs in local development (Docker), production (Kubernetes), and the desktop sidecar (local host OS) with minimal branching.

## Files covered

| File | Purpose |
|------|---------|
| `orchestration/__init__.py` | Re-exports. |
| `orchestration/base.py` | `BaseOrchestrator` ABC. |
| `orchestration/deployment_mode.py` | `DeploymentMode` enum. |
| `orchestration/factory.py` | `get_orchestrator()` plus per-project dispatch by `project.runtime`. |
| `orchestration/docker.py` | `DockerOrchestrator` for Docker Compose. |
| `orchestration/local.py` | `LocalOrchestrator` for the desktop sidecar: spawns host-OS subprocesses, manages stdout/stderr logs. |
| `orchestration/local_ports.py` | Port allocator for the local runtime: reserves free loopback ports per container. |
| `orchestration/kubernetes_orchestrator.py` | `KubernetesOrchestrator`: top-level K8s impl. |
| `orchestration/kubernetes/__init__.py` | Re-exports. |
| `orchestration/kubernetes/client.py` | K8s API client wrapper. |
| `orchestration/kubernetes/helpers.py` | Deployment manifest helpers. |
| `orchestration/kubernetes/manager.py` | K8s container lifecycle and cleanup. |

`factory.py` routes per-project based on `project.runtime` (`local` / `docker` / `k8s`) so cloud and desktop paths coexist in one codebase.

## Overview

The orchestration services handle the complete lifecycle of user project containers:

- **Project Lifecycle**: Start, stop, restart multi-container projects
- **File Operations**: Read, write, delete files in running containers
- **Command Execution**: Run shell commands in containers
- **Status Monitoring**: Check container health and readiness
- **Activity Tracking**: Track usage for idle cleanup
- **Cleanup Operations**: Hibernate or delete idle environments

## Architecture

```
BaseOrchestrator (Abstract)
├── DockerOrchestrator (Docker Compose)
│   ├── Uses shared volume: /projects
│   ├── Traefik routing: {project}-{container}.localhost
│   └── Direct filesystem access
├── KubernetesOrchestrator (Kubernetes)
│   ├── Uses per-project namespaces: proj-{uuid}
│   ├── NGINX Ingress: {project}-{container}.domain.com
│   └── btrfs CSI + Volume Hub (cache-node placement)
└── LocalOrchestrator (Desktop sidecar)
    ├── Host-OS subprocesses
    ├── 127.0.0.1 ports allocated by local_ports.py
    └── Stdout/stderr streamed to log files per container
```

## Core Files

### Base Interface
**File**: `orchestrator/app/services/orchestration/base.py` (440 lines)

Defines the abstract `BaseOrchestrator` class that both Docker and Kubernetes implementations must follow. This ensures feature parity across deployment modes.

```python
class BaseOrchestrator(ABC):
    """Abstract base for container orchestration."""

    @property
    @abstractmethod
    def deployment_mode(self) -> DeploymentMode:
        """Return deployment mode (DOCKER or KUBERNETES)."""
        pass

    @abstractmethod
    async def start_project(self, project, containers, connections, user_id, db):
        """Start all containers for a project."""
        pass

    @abstractmethod
    async def stop_project(self, project_slug, project_id, user_id):
        """Stop all containers for a project."""
        pass

    @abstractmethod
    async def read_file(self, user_id, project_id, container_name, file_path):
        """Read file from container filesystem."""
        pass

    @abstractmethod
    async def execute_command(self, user_id, project_id, container_name, command):
        """Execute command in container."""
        pass

    @abstractmethod
    async def cleanup_idle_environments(self, idle_timeout_minutes: int):
        """Clean up idle environments based on strategy."""
        pass
```

**Key Methods**:
- `start_project()` - Create and start all containers
- `stop_project()` - Stop and remove all containers
- `restart_project()` - Stop then start
- `get_project_status()` - Get status of all containers
- `start_container()` - Start individual container
- `stop_container()` - Stop individual container
- `read_file()` - Read file from container
- `write_file()` - Write file to container
- `execute_command()` - Run command in container
- `is_container_ready()` - Check if container is ready
- `cleanup_idle_environments()` - Hibernate/delete idle projects

### Factory Pattern
**File**: `orchestrator/app/services/orchestration/factory.py` (157 lines)

Provides centralized orchestrator creation with singleton caching:

```python
from services.orchestration import get_orchestrator

# Automatically selects Docker or Kubernetes based on config
orchestrator = get_orchestrator()

# Or explicitly request a specific mode
docker_orch = get_orchestrator(DeploymentMode.DOCKER)
k8s_orch = get_orchestrator(DeploymentMode.KUBERNETES)

# Check deployment mode
if is_docker_mode():
    print("Running in Docker Compose mode")

if is_kubernetes_mode():
    print("Running in Kubernetes mode")
```

**Helper Functions**:
- `get_orchestrator(mode=None)` - Get orchestrator instance
- `get_deployment_mode()` - Get current mode from config
- `is_docker_mode()` - Check if Docker mode
- `is_kubernetes_mode()` - Check if Kubernetes mode
- `OrchestratorFactory.clear_cache()` - Clear cache (testing only)

### Deployment Mode Enum
**File**: `orchestrator/app/services/orchestration/deployment_mode.py`

```python
class DeploymentMode(Enum):
    """Deployment mode enumeration."""
    DOCKER = "docker"
    KUBERNETES = "kubernetes"

    @classmethod
    def from_string(cls, mode: str) -> 'DeploymentMode':
        """Parse mode from string."""
        if mode.lower() == "docker":
            return cls.DOCKER
        elif mode.lower() in ["kubernetes", "k8s"]:
            return cls.KUBERNETES
        raise ValueError(f"Unknown mode: {mode}")

    @property
    def is_docker(self) -> bool:
        return self == DeploymentMode.DOCKER

    @property
    def is_kubernetes(self) -> bool:
        return self == DeploymentMode.KUBERNETES
```

## Docker Orchestrator

**File**: `orchestrator/app/services/orchestration/docker.py` (1,497 lines)

Implements container orchestration using Docker Compose for local development.

### Architecture

```
Docker Orchestrator
├── Compose Files: docker-compose-projects/{project-slug}.yml
├── Storage: Shared volume "tesslate-projects-data" mounted at /projects
├── Networking: Project-specific networks (tesslate-{project-slug})
├── Routing: Traefik for *.localhost URLs
└── File Access: Direct filesystem access (no kubectl exec needed)
```

### Key Features

#### 1. Dynamic Compose Generation

Creates docker-compose.yml files on-the-fly from Container models:

```python
async def _generate_compose_config(self, project, containers, connections, user_id):
    """Generate docker-compose.yml from database models."""

    # Project-specific isolated network
    network_name = f"tesslate-{project.slug}"

    compose_config = {
        'networks': {
            network_name: {'driver': 'bridge'}
        },
        'services': {},
        'volumes': {'tesslate-projects-data': {'external': True}}
    }

    for container in containers:
        service_name = self._sanitize_service_name(container.name)

        # Volume mount: Entire project to /app using subpath for security
        volumes = [{
            'type': 'volume',
            'source': 'tesslate-projects-data',
            'target': '/app',
            'volume': {'subpath': project.slug}  # Security: isolate projects
        }]

        # Traefik labels for routing
        labels = {
            'traefik.enable': 'true',
            'com.tesslate.routable': 'true',
            f'traefik.docker.network': network_name,
            'traefik.http.routers.{name}.rule': f'Host(`{project.slug}-{service_name}.localhost`)',
            'traefik.http.services.{name}.loadbalancer.server.port': str(port),
        }

        compose_config['services'][service_name] = {
            'image': 'tesslate-devserver:latest',
            'container_name': f"{project.slug}-{service_name}",
            'networks': [network_name],
            'volumes': volumes,
            'labels': labels,
            'restart': 'unless-stopped'
        }

    return compose_config
```

#### 2. Direct Filesystem Access

Unlike Kubernetes, Docker orchestrator has direct access to project files via shared volume:

```python
async def read_file(self, user_id, project_id, container_name, file_path, project_slug=None):
    """Read file directly from shared volume."""
    project_path = self.get_project_path(project_slug)  # /projects/{slug}
    full_path = project_path / file_path

    if not full_path.exists():
        return None

    async with aiofiles.open(full_path, 'r', encoding='utf-8') as f:
        return await f.read()
```

**No temp containers or kubectl exec needed** - just read from `/projects/{project-slug}/`.

#### 3. Traefik Integration

Connects main Traefik directly to project networks for routing:

```python
async def _connect_traefik_to_network(self, project_slug: str):
    """Connect main Traefik directly to project network."""
    network_name = f"tesslate-{project_slug}"

    await asyncio.create_subprocess_exec(
        'docker', 'network', 'connect', network_name, 'tesslate-traefik'
    )
```

This enables URLs like `http://my-app-frontend.localhost` and `http://my-app-backend.localhost`.

#### 4. Volume Subpath Security

Uses Docker Compose 2.23.0+ subpath feature to isolate projects:

```yaml
services:
  frontend:
    volumes:
      - type: volume
        source: tesslate-projects-data
        target: /app
        volume:
          subpath: my-app-k3x8n2  # Each project gets its own subtree
```

This prevents projects from accessing each other's files on the shared volume.

#### 5. Service Container Support

Handles databases and other service containers defined in `service_definitions.py`:

```python
async def _generate_service_container_config(self, project, container, service_name):
    """Generate config for Postgres, Redis, etc."""
    service_def = get_service(container.service_slug)

    if service_def.service_type == ServiceType.EXTERNAL:
        return None  # Skip external services

    volume_name = f"{project.slug}-{container.service_slug}-data"

    return {
        'service': {
            'image': service_def.docker_image,
            'volumes': [f"{volume_name}:{volume_path}" for volume_path in service_def.volumes],
            'environment': service_def.environment_vars,
            'restart': 'unless-stopped'
        },
        'volume': {volume_name: {'name': volume_name}}
    }
```

### Usage Example

```python
from services.orchestration import get_orchestrator

orchestrator = get_orchestrator()

# Start project
result = await orchestrator.start_project(
    project=project,
    containers=[frontend_container, backend_container],
    connections=[],
    user_id=user.id,
    db=db
)
# Returns: {
#   'status': 'running',
#   'containers': {
#       'Frontend': 'http://my-app-frontend.localhost',
#       'Backend': 'http://my-app-backend.localhost'
#   }
# }

# Read file from container
content = await orchestrator.read_file(
    user_id=user.id,
    project_id=project.id,
    container_name="Frontend",
    file_path="src/App.tsx",
    project_slug="my-app-k3x8n2"
)

# Execute command in container
output = await orchestrator.execute_command(
    user_id=user.id,
    project_id=project.id,
    container_name="Frontend",
    command=["npm", "install", "axios"],
    timeout=120
)
```

## Kubernetes Orchestrator

**File**: `orchestrator/app/services/orchestration/kubernetes_orchestrator.py`

Implements container orchestration using Kubernetes for production deployments.

### Architecture

```
Kubernetes Orchestrator
├── Namespaces: proj-{uuid} (per-project isolation)
├── Storage: Ephemeral PVC + S3 Sandwich pattern
├── Networking: NGINX Ingress with TLS
├── Resources: Deployments, Services, Ingresses per container
└── File Access: kubectl exec or K8s API (no direct filesystem)
```

### Key Features

#### 1. Per-Project Namespaces

Each project gets its own Kubernetes namespace for complete isolation:

```python
def _get_namespace(self, project_id: str) -> str:
    """Generate namespace name for project."""
    return f"proj-{project_id}"

async def start_project(self, project, containers, connections, user_id, db):
    """Start project in dedicated namespace."""
    namespace = self._get_namespace(str(project.id))

    # Create namespace with labels
    await self.k8s_client.create_namespace(
        name=namespace,
        labels={
            'tesslate.io/project-id': str(project.id),
            'tesslate.io/user-id': str(user_id),
            'tesslate.io/project-slug': project.slug
        }
    )

    # Create network policy for isolation
    await self._create_network_policy(namespace)

    # Create PVC for project storage
    await self._create_project_pvc(namespace, project)

    # Create deployment + service for each container
    for container in containers:
        await self._create_container_deployment(namespace, project, container)
        await self._create_container_service(namespace, container)

    # Create ingress for routing
    await self._create_project_ingress(namespace, project, containers)
```

#### 2. S3 Sandwich Pattern

Projects are stored in S3 and hydrated/dehydrated on pod start/stop:

```python
async def _create_container_deployment(self, namespace, project, container):
    """Create deployment with S3 hydration."""

    # Init container: Download project from S3
    init_containers = [{
        'name': 'hydrate-project',
        'image': settings.k8s_devserver_image,
        'command': ['/bin/sh', '-c'],
        'args': ['''
            echo "Checking S3 for project..."
            if python3 -c "
            from s3_manager import get_s3_manager
            import asyncio
            s3 = get_s3_manager()
            exists = asyncio.run(s3.project_exists(user_id, project_id))
            exit(0 if exists else 1)
            "; then
                echo "Hydrating from S3..."
                python3 -c "
                from s3_manager import get_s3_manager
                import asyncio
                s3 = get_s3_manager()
                asyncio.run(s3.download_project(user_id, project_id, '/app'))
                "
            else
                echo "No S3 backup found, using template"
                cp -r /templates/base/* /app/
            fi
        '''],
        'volumeMounts': [{'name': 'project-source', 'mountPath': '/app'}]
    }]

    # Main container: Development server
    containers = [{
        'name': 'dev-server',
        'image': settings.k8s_devserver_image,
        'command': ['npm', 'run', 'dev'],
        'volumeMounts': [{'name': 'project-source', 'mountPath': '/app'}],
        'lifecycle': {
            'preStop': {
                'exec': {
                    'command': ['/bin/sh', '-c', '''
                        echo "Dehydrating to S3..."
                        python3 -c "
                        from s3_manager import get_s3_manager
                        import asyncio
                        s3 = get_s3_manager()
                        asyncio.run(s3.upload_project(user_id, project_id, '/app'))
                        "
                    ''']
                }
            }
        }
    }]

    deployment = {
        'apiVersion': 'apps/v1',
        'kind': 'Deployment',
        'metadata': {'name': f'dev-{container.directory}', 'namespace': namespace},
        'spec': {
            'replicas': 1,
            'selector': {'matchLabels': {'app': f'dev-{container.directory}'}},
            'template': {
                'spec': {
                    'initContainers': init_containers,
                    'containers': containers,
                    'volumes': [{
                        'name': 'project-source',
                        'persistentVolumeClaim': {'claimName': 'project-pvc'}
                    }]
                }
            }
        }
    }

    await self.k8s_client.create_deployment(deployment)
```

**Lifecycle**:
1. **Hydration** (init container): Download project from S3 if exists, else use template
2. **Runtime**: Fast local I/O on PVC for development
3. **Dehydration** (preStop hook): Upload project to S3 before pod termination

#### 3. File Operations via K8s API

Unlike Docker's direct filesystem access, K8s requires API calls:

```python
async def read_file(self, user_id, project_id, container_name, file_path, project_slug=None):
    """Read file via kubectl exec."""
    namespace = self._get_namespace(str(project_id))

    # Get pod name from deployment
    deployment_name = self._get_deployment_name(container_name)
    pods = await self.k8s_client.list_namespaced_pod(
        namespace=namespace,
        label_selector=f'app={deployment_name}'
    )

    if not pods.items:
        return None

    pod_name = pods.items[0].metadata.name

    # Execute cat command in pod
    command = ['cat', f'/app/{file_path}']
    output = await self.k8s_client.exec_in_pod(
        namespace=namespace,
        pod_name=pod_name,
        container='dev-server',
        command=command
    )

    return output
```

#### 4. NGINX Ingress with TLS

Creates ingress rules for external access:

```python
async def _create_project_ingress(self, namespace, project, containers):
    """Create NGINX ingress with TLS."""

    rules = []
    for container in containers:
        hostname = f"{project.slug}-{container.directory}.{settings.app_domain}"
        rules.append({
            'host': hostname,
            'http': {
                'paths': [{
                    'path': '/',
                    'pathType': 'Prefix',
                    'backend': {
                        'service': {
                            'name': f'dev-{container.directory}',
                            'port': {'number': 3000}
                        }
                    }
                }]
            }
        })

    ingress = {
        'apiVersion': 'networking.k8s.io/v1',
        'kind': 'Ingress',
        'metadata': {
            'name': 'project-ingress',
            'namespace': namespace,
            'annotations': {
                'cert-manager.io/cluster-issuer': 'letsencrypt-prod',
                'nginx.ingress.kubernetes.io/proxy-body-size': '100m',
                'nginx.ingress.kubernetes.io/proxy-hide-headers': 'X-Frame-Options'
            }
        },
        'spec': {
            'ingressClassName': 'nginx',
            'tls': [{
                'hosts': [rule['host'] for rule in rules],
                'secretName': 'tesslate-wildcard-tls'
            }],
            'rules': rules
        }
    }

    await self.k8s_client.create_ingress(ingress)
```

#### 5. Cleanup Strategies

Kubernetes orchestrator supports two cleanup modes:

**S3 Mode (Hibernation)**:
```python
async def _cleanup_s3_mode(self, idle_timeout_minutes: int):
    """Delete idle environments (triggers S3 upload via preStop hook)."""
    k8s_environments = await self.k8s_client.list_dev_environments()

    for env in k8s_environments:
        idle_time = time.time() - env['last_activity']
        if idle_time > idle_timeout_minutes * 60:
            # Delete namespace (preStop hook uploads to S3)
            await self.stop_container(env['project_id'], env['user_id'])
            logger.info(f"Hibernated {env['project_key']} to S3")
```

**Persistent PVC Mode (Two-Tier)**:
```python
async def _cleanup_persistent_mode(self, idle_timeout_minutes: int):
    """Two-tier cleanup: Scale to 0, then delete after 24h."""

    # Tier 1: Scale to 0 after idle_timeout_minutes
    for env in k8s_environments:
        if env['idle_time'] > idle_timeout_minutes * 60 and env['replicas'] > 0:
            await self.k8s_client.scale_deployment(
                user_id=env['user_id'],
                project_id=env['project_id'],
                replicas=0
            )
            logger.info(f"Scaled down {env['project_key']}")

    # Tier 2: Delete resources after 24 hours at 0 replicas
    for env in paused_environments:
        if env['paused_time'] > 24 * 60 * 60:
            await self.stop_container(env['project_id'], env['user_id'])
            logger.info(f"Deleted {env['project_key']} after 24h pause")
```

### Usage Example

```python
from services.orchestration import get_orchestrator

orchestrator = get_orchestrator()

# Start project (creates namespace, deployments, services, ingress)
result = await orchestrator.start_project(
    project=project,
    containers=[frontend_container, backend_container],
    connections=[],
    user_id=user.id,
    db=db
)
# Returns: {
#   'status': 'running',
#   'namespace': 'proj-abc123',
#   'containers': {
#       'Frontend': 'https://my-app-frontend.your-domain.com',
#       'Backend': 'https://my-app-backend.your-domain.com'
#   }
# }

# Read file via kubectl exec
content = await orchestrator.read_file(
    user_id=user.id,
    project_id=project.id,
    container_name="Frontend",
    file_path="src/App.tsx"
)

# Execute command via kubectl exec
output = await orchestrator.execute_command(
    user_id=user.id,
    project_id=project.id,
    container_name="Frontend",
    command=["npm", "install", "axios"],
    timeout=120
)
```

## Kubernetes Client & Helpers

### Client Wrapper
**File**: `orchestrator/app/services/orchestration/kubernetes/client.py`

Wraps Kubernetes Python client with async support and error handling:

```python
class KubernetesClient:
    """Async wrapper for Kubernetes API client."""

    def __init__(self):
        """Initialize K8s client with proper config loading."""
        if os.path.exists('/var/run/secrets/kubernetes.io/serviceaccount'):
            # Running in-cluster (production)
            config.load_incluster_config()
        else:
            # Running locally (development)
            config.load_kube_config()

        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
        self.networking_v1 = client.NetworkingV1Api()

    async def create_namespace(self, name: str, labels: Dict):
        """Create namespace asynchronously."""
        namespace = client.V1Namespace(
            metadata=client.V1ObjectMeta(name=name, labels=labels)
        )
        await asyncio.to_thread(self.core_v1.create_namespace, namespace)

    async def exec_in_pod(self, namespace: str, pod_name: str, container: str, command: List[str]):
        """Execute command in pod using stream.stream."""
        resp = await asyncio.to_thread(
            stream.stream,
            self.core_v1.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace=namespace,
            container=container,
            command=command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False
        )
        return resp
```

### Manifest Helpers
**File**: `orchestrator/app/services/orchestration/kubernetes/helpers.py`

Generates Kubernetes manifests from project configuration:

```python
def create_deployment_manifest(
    project_id: UUID,
    user_id: UUID,
    container: Container,
    namespace: str
) -> Dict:
    """Generate deployment manifest with init container for S3 hydration."""

    deployment = {
        'apiVersion': 'apps/v1',
        'kind': 'Deployment',
        'metadata': {
            'name': f'dev-{container.directory}',
            'namespace': namespace,
            'labels': {
                'tesslate.io/project-id': str(project_id),
                'tesslate.io/container-directory': container.directory
            }
        },
        'spec': {
            'replicas': 1,
            'selector': {'matchLabels': {'app': f'dev-{container.directory}'}},
            'template': {
                'metadata': {'labels': {'app': f'dev-{container.directory}'}},
                'spec': {
                    'initContainers': [create_hydration_init_container(...)],
                    'containers': [create_dev_server_container(...)],
                    'volumes': [{'name': 'project-source', 'persistentVolumeClaim': {'claimName': 'project-pvc'}}]
                }
            }
        }
    }

    return deployment
```

### Container Manager
**File**: `orchestrator/app/services/orchestration/kubernetes/manager.py` (555 lines)

Manages container lifecycle and cleanup operations:

```python
class KubernetesContainerManager:
    """Manages K8s container lifecycle and cleanup."""

    def __init__(self):
        self.environments: Dict[str, Dict] = {}
        self.activity_tracker: Dict[str, float] = {}
        self.paused_at_tracker: Dict[str, float] = {}

    async def start_container(self, project_path, project_id, user_id, project_slug):
        """Create K8s resources for container."""
        k8s_client = get_k8s_client()
        environment_info = await k8s_client.create_dev_environment(...)
        self.environments[project_key] = environment_info
        return environment_info["url"]

    async def cleanup_idle_environments(self, idle_timeout_minutes: int):
        """Cleanup based on storage mode (S3 or persistent PVC)."""
        if settings.k8s_use_s3_storage:
            return await self._cleanup_s3_mode(idle_timeout_minutes)
        else:
            return await self._cleanup_persistent_mode(idle_timeout_minutes)
```

## Comparison: Docker vs Kubernetes

| Feature | Docker Orchestrator | Kubernetes Orchestrator |
|---------|-------------------|------------------------|
| **Isolation** | Project networks | Namespaces with NetworkPolicy |
| **Storage** | Shared volume with subpaths | PVC + S3 Sandwich |
| **File Access** | Direct filesystem | kubectl exec or K8s API |
| **Networking** | Traefik (*.localhost) | NGINX Ingress (*.domain.com) |
| **TLS** | No (localhost) | Yes (cert-manager) |
| **Cleanup** | Two-tier (pause, delete) | S3 hibernation or scale-to-0 |
| **Resource Limits** | Docker limits | K8s ResourceQuota |
| **Health Checks** | Docker healthcheck | K8s liveness/readiness probes |
| **Scaling** | Manual restart | Scale replicas to 0/1 |
| **Multi-Region** | Regional Traefik | K8s multi-cluster |

## Common Usage Patterns

### Pattern 1: Mode-Agnostic Operations

Write code that works in both modes using the abstract interface:

```python
from services.orchestration import get_orchestrator

async def deploy_user_project(project_id: UUID, user_id: UUID, db: AsyncSession):
    """Deploy project regardless of orchestration mode."""
    orchestrator = get_orchestrator()  # Auto-selects mode

    # These methods work identically in Docker and K8s
    result = await orchestrator.start_project(project, containers, connections, user_id, db)
    content = await orchestrator.read_file(user_id, project_id, "Frontend", "package.json")
    output = await orchestrator.execute_command(user_id, project_id, "Frontend", ["npm", "install"])

    return result
```

### Pattern 2: Mode-Specific Logic

When you need mode-specific behavior:

```python
from services.orchestration import get_orchestrator, is_kubernetes_mode, is_docker_mode

async def handle_project_files(project_id: UUID):
    orchestrator = get_orchestrator()

    if is_docker_mode():
        # Docker: Direct filesystem access is fast
        files = await orchestrator.get_files_with_content(project.slug, max_files=500)
        return files

    elif is_kubernetes_mode():
        # K8s: kubectl exec is slower, use smaller batch
        files = await orchestrator.get_files_with_content(project.slug, max_files=100)
        return files
```

### Pattern 3: Activity Tracking for Cleanup

Track user activity to enable intelligent cleanup:

```python
from services.orchestration import get_orchestrator

async def handle_user_request(user_id: UUID, project_id: str):
    """Handle request and track activity for cleanup."""
    orchestrator = get_orchestrator()

    # Track activity (used by cleanup task)
    orchestrator.track_activity(user_id, project_id)

    # Perform operation
    result = await orchestrator.execute_command(...)

    return result
```

### Pattern 4: Background Cleanup Task

Run periodic cleanup of idle environments:

```python
from services.orchestration import get_orchestrator

async def cleanup_idle_projects_task():
    """Background task to cleanup idle environments."""
    orchestrator = get_orchestrator()

    # Cleanup environments idle for 30+ minutes
    cleaned = await orchestrator.cleanup_idle_environments(idle_timeout_minutes=30)

    logger.info(f"Cleaned up {len(cleaned)} idle environments")
    # Docker: Scaled to 0 or deleted
    # K8s: Hibernated to S3 or scaled to 0
```

## Configuration

### Docker Mode Settings

```bash
# .env
DEPLOYMENT_MODE=docker
USE_DOCKER_VOLUMES=true  # Use volumes vs bind mounts
```

### Kubernetes Mode Settings

```bash
# .env
DEPLOYMENT_MODE=kubernetes

# Image configuration
K8S_DEVSERVER_IMAGE=tesslate-devserver:latest
K8S_IMAGE_PULL_SECRET=  # Empty for local images

# Storage strategy
K8S_USE_S3_STORAGE=true  # Enable S3 Sandwich pattern
S3_BUCKET_NAME=tesslate-project-storage
S3_ENDPOINT_URL=  # Empty for AWS S3, set for MinIO/DigitalOcean

# Resources
K8S_STORAGE_CLASS=tesslate-block-storage
K8S_ENABLE_POD_AFFINITY=true  # Co-locate multi-container projects
```

## Best Practices

1. **Always use the factory**: Use `get_orchestrator()` instead of instantiating directly
2. **Track activity**: Call `orchestrator.track_activity()` on user interactions
3. **Handle both modes**: Write mode-agnostic code when possible
4. **Async everywhere**: All orchestrator methods are async - don't forget `await`
5. **Error handling**: Wrap orchestrator calls in try/except with logging
6. **Cleanup task**: Run `cleanup_idle_environments()` in background task
7. **File operations**: Batch file reads/writes to minimize kubectl exec calls (K8s)
8. **Resource limits**: Set appropriate CPU/memory limits for user containers

## Troubleshooting

### Docker Issues

**Problem**: Container not accessible at *.localhost
- Check Traefik is connected to project network
- Verify docker-compose.yml has correct labels
- Check `docker network ls` for project network

**Problem**: File operations fail
- Verify shared volume `tesslate-projects-data` exists
- Check volume mount in docker-compose.yml
- Ensure project directory exists in volume

### Kubernetes Issues

**Problem**: ImagePullBackOff
- Check `K8S_DEVSERVER_IMAGE` is correct
- Verify image exists: `kubectl get pods -o yaml`
- Check `K8S_IMAGE_PULL_SECRET` if using private registry

**Problem**: File operations slow
- Normal - kubectl exec has overhead
- Batch operations when possible
- Consider caching frequently accessed files

**Problem**: Project not hydrating from S3
- Check init container logs: `kubectl logs <pod> -c hydrate-project`
- Verify S3 credentials and bucket
- Check S3Manager can access bucket

## Related Documentation

- [s3-manager.md](./s3-manager.md) - S3 Sandwich pattern details
- [shell-sessions.md](./shell-sessions.md) - Shell sessions use orchestrator
- [git-manager.md](./git-manager.md) - Git operations use orchestrator.execute_command()
- [../routers/projects.md](../routers/projects.md) - Project API uses orchestrator
