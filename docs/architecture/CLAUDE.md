# Architecture Context for AI Agents

**Purpose**: This context helps AI agents understand Tesslate Studio's system architecture, component interactions, and deployment patterns when working with the codebase.

## When to Load This Context

Load this architecture context when:

1. **First-time codebase understanding** - Understanding how systems connect
2. **Cross-system debugging** - Issues spanning frontend, backend, and containers
3. **Architecture changes** - Modifying how components interact
4. **Deployment issues** - Problems with Docker/K8s orchestration
5. **Performance optimization** - Understanding bottlenecks and data flow
6. **New feature planning** - Ensuring consistency with architecture principles

**Do NOT load** for:
- Simple bug fixes in a single file
- UI-only changes
- Database schema-only changes
- Isolated tool/utility modifications

## System Architecture Overview

Tesslate Studio uses a **multi-tier architecture** with clear separation of concerns:

```
User Browser (React)
    ↓ HTTP/WebSocket
API Pod (FastAPI)
    ↓ Database queries          ↓ Task queue
PostgreSQL                    Redis (Pub/Sub, Streams, ARQ)
                                ↓ Job execution
                            Worker Pod (ARQ)
    ↓ Container orchestration
Docker Compose OR Kubernetes
    ↓ User project containers
Isolated Dev Environments
```

## Key Source Files

### Backend (Orchestrator)

| File | Path | Purpose |
|------|------|---------|
| Main Entry | `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/main.py` | FastAPI app initialization, middleware, routers |
| Configuration | `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/config.py` | Environment settings, deployment mode config |
| Database Models | `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/models.py` | SQLAlchemy models (User, Project, Container, etc.) |
| API Schemas | `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/schemas.py` | Pydantic request/response schemas |

### Frontend (App)

| File | Path | Purpose |
|------|------|---------|
| App Entry | `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/App.tsx` | React router, auth context, main layout |
| API Client | `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/lib/api.ts` | HTTP client for backend communication |
| Auth Context | `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/contexts/AuthContext.tsx` | User authentication state |

### Container Orchestration

| File | Path | Purpose |
|------|------|---------|
| K8s Orchestrator | `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/kubernetes_orchestrator.py` | Kubernetes container lifecycle |
| K8s Client | `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/kubernetes/client.py` | Kubernetes API wrapper |
| K8s Helpers | `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/kubernetes/helpers.py` | Manifest generation (Deployment, Service, Ingress) |
| S3 Manager | `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/s3_manager.py` | S3 hydration/dehydration for K8s |

### AI Agent System

| File | Path | Purpose |
|------|------|---------|
| Stream Agent | `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/agent/stream_agent.py` | Streaming agent with tool execution |
| Agent Factory | `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/agent/factory.py` | Agent instantiation from config |
| Agent Base | `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/agent/base.py` | Abstract agent interface |
| Agent Tools | `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/agent/tools/` | File ops, bash, session, fetch, etc. |

### API Routers

| Router | Path | Purpose |
|--------|------|---------|
| Projects | `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/projects.py` | Project CRUD, start/stop containers |
| Chat | `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/chat.py` | Agent chat, streaming responses |
| Deployments | `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/deployments.py` | Vercel/Netlify/Cloudflare |
| Git | `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/git.py` | Git operations (commit, push, pull) |
| Billing | `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/billing.py` | Stripe subscriptions |

## Related Context Documents

Load these contexts for system-specific deep dives:

1. **[Orchestrator Context](../orchestrator/CLAUDE.md)** - Backend API implementation details
2. **[Frontend Context](../app/CLAUDE.md)** - React UI, state management, components
3. **[Infrastructure Context](../infrastructure/CLAUDE.md)** - Kubernetes manifests, deployment pipelines

## Architecture Principles

### 1. Non-Blocking Operations

**Principle**: User requests should never block on long-running tasks.

**Implementation**:
- Background tasks for project setup, builds, deployments
- WebSocket streaming for agent responses
- Async/await for all I/O operations
- Database-based activity tracking (no in-memory state)

**Example**:
```python
# ❌ BAD - Blocks user request
def create_project():
    project = db_create_project()
    setup_containers()  # Takes 30+ seconds
    return project

# ✅ GOOD - Returns immediately
def create_project():
    project = db_create_project()
    background_task(setup_containers)  # Non-blocking
    return project
```

### 2. Scalable Architecture

**Principle**: System should handle horizontal scaling without code changes.

**Implementation**:
- Stateless backend services (no in-memory sessions)
- Database-based coordination (Project.last_activity)
- S3 for shared project storage in K8s mode
- Per-project namespace isolation

**Key Settings** (from `config.py`):
```python
k8s_namespace_per_project: bool = True  # Enable namespace isolation
k8s_use_s3_storage: bool = True        # S3 Sandwich pattern
k8s_enable_pod_affinity: bool = True   # Multi-container sharing
```

### 3. Container Isolation

**Principle**: Projects must never interfere with each other.

**Implementation**:
- Docker: Separate compose files, isolated networks
- K8s: Per-project namespaces with NetworkPolicy
- Pod affinity: Multi-container projects share RWO storage
- Resource limits: CPU/memory quotas per container

**K8s Network Policy** (from `kubernetes/helpers.py`):
```python
# Zero cross-project communication
network_policy = {
    "apiVersion": "networking.k8s.io/v1",
    "kind": "NetworkPolicy",
    "spec": {
        "podSelector": {},
        "policyTypes": ["Ingress", "Egress"],
        "ingress": [{"from": [{"namespaceSelector": ...}]}],
        "egress": [...]  # Internet + cluster DNS only
    }
}
```

## Deployment Modes

Tesslate Studio supports **two deployment modes** configured via `DEPLOYMENT_MODE` environment variable:

### Docker Mode (Local Development)

**When**: Running on developer machine with Docker Desktop

**Configuration**:
```bash
DEPLOYMENT_MODE=docker
DEV_SERVER_BASE_URL=http://localhost
```

**Architecture**:
- Traefik routes `*.localhost` to containers
- Project files on local filesystem (`users/{user_id}/{project_slug}/`)
- Docker Compose for multi-container projects
- Direct volume mounts for fast file access

**Key Code**: No Docker orchestrator exists (legacy removed). Check CLAUDE.md for details.

### Kubernetes Mode (Production)

**When**: Running on K8s cluster (Minikube, AWS EKS, DigitalOcean)

**Configuration**:
```bash
DEPLOYMENT_MODE=kubernetes
K8S_DEVSERVER_IMAGE=tesslate-devserver:latest
K8S_USE_S3_STORAGE=true
S3_BUCKET_NAME=tesslate-project-storage-prod
```

**Architecture**:
- NGINX Ingress routes subdomains to pods
- S3 Sandwich pattern (hydrate from S3 → PVC → dehydrate to S3)
- Per-project namespaces (`proj-{uuid}`)
- NetworkPolicy isolation

**Key Code**: `kubernetes_orchestrator.py`, `kubernetes/client.py`, `s3_manager.py`

## Data Flow Patterns

### Agent Chat Flow

```
1. User types message in frontend chat UI
   ↓
2. Frontend: POST /api/chat/agent/stream (SSE) or WebSocket message
   ↓
3. Backend: chat.py builds AgentTaskPayload
   ├─ Create/reuse Chat session
   ├─ Build project context (agent_context.py)
   └─ Enqueue to ARQ Redis queue
   ↓
4. Worker: worker.py picks up task
   ├─ Acquire project lock (prevent concurrent runs)
   ├─ Create placeholder Message
   ├─ Run agent loop with progressive persistence
   │  ├─ INSERT AgentStep per iteration
   │  ├─ Publish events to Redis Stream
   │  └─ Check cancellation between iterations
   ├─ Finalize Message with summary
   └─ Release lock + optional webhook callback
   ↓
5. Redis Stream → API Pod → WebSocket → Frontend
   ↓
6. Frontend: Renders agent steps in real-time
```

### External Agent API Flow

```
1. External client: POST /api/external/agent/invoke (Bearer token)
   ↓
2. Backend: Authenticate API key, validate project scope
   ↓
3. Backend: Build context + enqueue ARQ task (same as browser flow)
   ↓
4. Client receives task_id + events_url immediately
   ↓
5. Client: GET /api/external/agent/events/{task_id} (SSE)
   └─ OR: GET /api/external/agent/status/{task_id} (polling)
   ↓
6. Worker executes agent, streams events via Redis
   ↓
7. Optional: POST webhook_url with final results
```

### Container Start Flow

```
1. User clicks "Start" button in frontend
   ↓
2. Frontend: POST /api/projects/{id}/start
   ↓
3. Backend: projects.py router receives request
   ↓
4. Backend: Check deployment mode (config.py)
   ├─ Docker mode: Legacy removed (check CLAUDE.md)
   └─ K8s mode: kubernetes_orchestrator.py
   ↓
5. K8s Orchestrator:
   ├─ Create namespace (proj-{uuid})
   ├─ Create PVC (shared storage)
   ├─ Create file-manager pod (always running)
   ├─ Hydrate from S3 (if project exists)
   ├─ Create dev container Deployment + Service
   ├─ Create Ingress rules
   └─ Return container URLs
   ↓
6. Frontend: Polls /api/projects/{id}/status
   ↓
7. User accesses container at subdomain URL
```

### File Operations Flow

```
1. User edits file in Monaco editor
   ↓
2. Frontend: PUT /api/projects/{id}/files/{path}
   ↓
3. Backend: projects.py receives request
   ↓
4. Backend: Check deployment mode
   ├─ Docker mode: Write directly to filesystem
   └─ K8s mode: Exec into file-manager pod
   ↓
5. K8s mode: Execute write command in pod
   ↓
6. File persisted on PVC
   ↓
7. On project close: Dehydrate to S3
```

## Key Environment Variables

### Common Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `SECRET_KEY` | JWT signing, encryption | ❌ Required |
| `DATABASE_URL` | PostgreSQL connection | ❌ Required |
| `DEPLOYMENT_MODE` | `docker` or `kubernetes` | `docker` |
| `LOG_LEVEL` | Logging verbosity | `INFO` |
| `REDIS_URL` | Redis connection string | `` (disabled) |
| `APP_DOMAIN` | Main app domain | `localhost` |
| `CORS_ORIGINS` | Allowed CORS origins | `` |

### Docker Mode Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `DEV_SERVER_BASE_URL` | Base URL for containers | ❌ Required |

### Kubernetes Mode Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `K8S_DEVSERVER_IMAGE` | Dev container image | `registry.digitalocean.com/.../tesslate-devserver:latest` |
| `K8S_IMAGE_PULL_SECRET` | Registry credentials | `tesslate-container-registry-nyc3` |
| `K8S_USE_S3_STORAGE` | Enable S3 Sandwich | `true` |
| `K8S_STORAGE_CLASS` | PVC storage class | `tesslate-block-storage` |
| `K8S_ENABLE_POD_AFFINITY` | Multi-container sharing | `true` |
| `S3_ENDPOINT_URL` | S3 endpoint | `https://s3.us-east-1.amazonaws.com` |
| `S3_BUCKET_NAME` | S3 bucket for projects | `tesslate-projects` |
| `S3_ACCESS_KEY_ID` | S3 credentials | ❌ Required (K8s) |
| `S3_SECRET_ACCESS_KEY` | S3 credentials | ❌ Required (K8s) |

## Quick Reference Commands

### Check Deployment Mode

```python
from app.config import get_settings
settings = get_settings()

if settings.is_docker_mode:
    # Docker-specific code
    pass
elif settings.is_kubernetes_mode:
    # K8s-specific code
    pass
```

### Access Orchestrator

```python
from app.services.orchestration import get_orchestrator

orchestrator = get_orchestrator()  # Returns KubernetesOrchestrator based on mode
await orchestrator.start_project(project_id, db)
```

### Database Queries

```python
from app.database import AsyncSessionLocal
from app.models import Project, Container

async with AsyncSessionLocal() as db:
    project = await db.get(Project, project_id)
    containers = await db.execute(
        select(Container).where(Container.project_id == project_id)
    )
```

## Common Pitfalls

### 1. Forgetting Deployment Mode

❌ **Wrong**: Hardcoding Docker-specific logic
```python
project_path = f"users/{user_id}/{project_slug}/"
```

✅ **Correct**: Check deployment mode
```python
from app.services.orchestration import is_docker_mode, is_kubernetes_mode

if is_docker_mode():
    project_path = f"users/{user_id}/{project_slug}/"
elif is_kubernetes_mode():
    # Files are on PVC, accessed via pod exec
    pass
```

### 2. Blocking on Long Operations

❌ **Wrong**: Waiting for container startup
```python
await orchestrator.start_project(project_id, db)
# Blocks for 30+ seconds
return {"status": "started"}
```

✅ **Correct**: Return immediately, poll status
```python
background_task(orchestrator.start_project, project_id, db)
return {"status": "starting"}  # Frontend polls /status
```

### 3. In-Memory State (Breaks Scaling)

❌ **Wrong**: Tracking state in memory
```python
active_projects = {}  # Lost on pod restart!
```

✅ **Correct**: Use database
```python
project.last_activity = datetime.utcnow()
await db.commit()
```

## Testing Architecture Changes

When modifying architecture:

1. **Test both deployment modes**:
   ```bash
   # Docker mode
   DEPLOYMENT_MODE=docker pytest tests/

   # K8s mode (requires minikube)
   DEPLOYMENT_MODE=kubernetes pytest tests/
   ```

2. **Test scaling scenarios**:
   - Multiple backend replicas
   - Project access from different pods
   - Database connection pooling

3. **Test failure modes**:
   - Pod evictions (K8s)
   - Network partitions
   - S3 unavailability

4. **Performance test**:
   - Agent response latency
   - Container startup time
   - File operation throughput

## Next Steps

After understanding architecture:

1. Read **system-specific CLAUDE.md** for implementation details
2. Review **[data-flow.md](./data-flow.md)** for detailed request patterns
3. Check **[deployment-modes.md](./deployment-modes.md)** for configuration
4. Start development using **[../guides/development.md](../guides/development.md)**
