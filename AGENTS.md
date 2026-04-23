You are a senior level coding agent. You will apply real world solutions to all the problems, fixing them in such a way where you do not cheat the solution, break existing functionality, and are scoped in. The solutions you write must be scalable and for the future, not fixing or hardcoding.

Always read through the docs/ to find items it is a knowledgegraph

Use subagents generously if you are doing bulk task items that have a small / atomic scope. 

don't do conditional logic for k8s and docker implementation differences. try to keep it as similar as possible unless if a platform requires differeces. Prioritize the k8s (keep that logic more intact than docker. )

On windows use MSYS_NO_PATHCONV=1 while running kubectl or docker exec commands. 
The ECR IS <AWS_ACCOUNT_ID> not <AWS_ACCOUNT_ID>

CRITICAL -- ENSURE ALL CHANGES ARE NON-BLOCKING

Everything u do or write should be non-blocking so certain actions don't hold up other people on our software. 

# OpenSail

When I have an issue, fix it for the next time it happens in a general, scalable way. For example, if a container fails on startup, ensure all future container startups work 100%.

## What is OpenSail?

AI-powered web application builder that lets users create, edit, deploy, and manage full-stack apps using natural language. Users describe what they want, an AI agent writes the code, and the platform handles containerized deployment.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    OpenSail                                 │
├─────────────────────────────────────────────────────────────┤
│  Frontend (app/)           │   Orchestrator (orchestrator/) │
│  React + Vite + TypeScript │   FastAPI + Python             │
│  - Monaco Editor           │   - Auth (JWT/OAuth)           │
│  - Live Preview            │   - Project Management         │
│  - Chat UI                 │   - AI Agent System            │
│  - File Browser            │   - Container Orchestration    │
├─────────────────────────────────────────────────────────────┤
│  Redis                │  ARQ Worker                          │
│  - Pub/Sub + Streams  │  - Distributed agent execution       │
│  - Task queue (ARQ)   │  - Progressive step persistence      │
│  - Distributed locks  │  - Webhook callbacks                 │
├─────────────────────────────────────────────────────────────┤
│  PostgreSQL        │  Docker/Kubernetes Container Manager   │
│  (User data,       │  (User project environments)           │
│   projects, chat)  │  - Per-project isolation               │
└─────────────────────────────────────────────────────────────┘
```

## Technology Stack

| Layer | Tech |
|-------|------|
| Frontend | React 19, TypeScript, Vite, Tailwind, Monaco Editor |
| Backend | FastAPI, Python 3.11, SQLAlchemy, LiteLLM |
| Database | PostgreSQL (asyncpg) |
| Task Queue | Redis 7.x, ARQ |
| Containers | Docker Compose (dev), Kubernetes (prod) |
| Routing | Traefik (Docker), NGINX Ingress (K8s) |
| AI | LiteLLM → OpenAI/Anthropic models |
| Payments | Stripe |

## Key Code Paths

### 1. Project Creation
```
POST /api/projects → routers/projects.py
  └─> _perform_project_setup (background task)
      ├─ Create project directory
      ├─ Copy template files from base
      ├─ Generate docker-compose.yml OR K8s manifests
      └─ Return project slug (e.g., "my-app-k3x8n2")
```

### 2. Agent Chat (AI Code Generation)
```
POST /api/chat/agent/stream → routers/chat.py
  ├─> Build AgentTaskPayload (agent_context.py)
  │     └─> Project info, git status, chat history, TESSLATE.md
  ├─> Enqueue to ARQ Redis queue
  │     └─> Worker picks up task (worker.py)
  │           ├─ Acquire project lock (prevent concurrent runs)
  │           ├─ Run agent loop with progressive persistence
  │           │   ├─ INSERT AgentStep per iteration
  │           │   ├─ Publish events to Redis Stream
  │           │   └─ Check cancellation signal between iterations
  │           ├─ Finalize Message with summary
  │           └─ Release lock + optional webhook callback
  └─> Redis Stream → WebSocket → Client renders steps in real-time
```

### 2b. External Agent API
```
POST /api/external/agent/invoke → routers/external_agent.py
  ├─> Authenticate via Bearer token (API key)
  ├─> Build AgentTaskPayload (same as browser flow)
  ├─> Enqueue to ARQ Redis queue
  └─> Return task_id + events_url immediately

GET /api/external/agent/events/{task_id} (SSE)
  └─> Subscribe to Redis Stream for real-time events

GET /api/external/agent/status/{task_id} (Polling)
  └─> Query TaskManager for current status
```

### 3. Container Lifecycle
```
POST /api/projects/{id}/start → routers/projects.py

DOCKER MODE (config.DEPLOYMENT_MODE="docker"):
  └─> DockerComposeOrchestrator.start_project()
      ├─ Generate docker-compose.yml from Container models
      ├─ docker-compose up -d
      ├─ Connect to Traefik network
      └─> URLs: {container}.localhost

KUBERNETES MODE (config.DEPLOYMENT_MODE="kubernetes"):
  └─> KubernetesOrchestrator.start_project()
      ├─ Create namespace (proj-{uuid})
      ├─ Create PVC (shared storage)
      ├─ Create Deployment + Service per container
      ├─ Create Ingress rules
      └─> URLs: {container}.domain.com
```

### 4. External Deployment (Vercel/Netlify/Cloudflare)
```
POST /api/deployments → routers/deployments.py
  ├─> Get provider OAuth token from DeploymentCredential
  ├─> Build project locally (npm build)
  ├─> Push to git repo
  └─> Provider auto-deploys → Returns live URL
```

## Directory Structure

```
tesslate-studio/
├── orchestrator/              # FastAPI backend
│   └── app/
│       ├── main.py           # App entry, middleware setup
│       ├── models.py         # SQLAlchemy models (User, Project, Container, Chat, etc.)
│       ├── schemas.py        # Pydantic request/response schemas
│       ├── config.py         # Settings (env vars, deployment mode)
│       ├── routers/          # API endpoints
│       │   ├── projects.py   # Project CRUD, start/stop containers
│       │   ├── chat.py       # Agent chat, streaming responses
│       │   ├── billing.py    # Stripe subscriptions
│       │   ├── deployments.py # Vercel/Netlify/Cloudflare
│       │   ├── git.py        # Git operations
│       │   ├── external_agent.py # External agent API (API keys, SSE, webhooks)
│       │   └── ...
│       ├── services/
│       │   ├── docker_compose_orchestrator.py  # Docker container mgmt
│       │   ├── orchestration/
│       │   │   ├── kubernetes_orchestrator.py  # K8s container mgmt
│       │   │   └── kubernetes/
│       │   │       ├── client.py               # K8s API client wrapper
│       │   │       └── helpers.py              # Deployment manifests
│       │   ├── snapshot_manager.py             # EBS VolumeSnapshot for project persistence
│       │   ├── litellm_service.py              # AI model routing
│       │   ├── pubsub.py                   # Cross-pod Redis pub/sub + streams
│       │   ├── distributed_lock.py         # Redis-based distributed locks
│       │   ├── agent_context.py            # Agent execution context builder
│       │   ├── agent_task.py               # Agent task payload serialization
│       │   ├── session_router.py           # Cross-pod shell session routing
│       │   └── ...
│       ├── worker.py         # ARQ worker for agent tasks
│       ├── auth_external.py  # API key authentication
│       └── agent/            # AI agent system
│           ├── base.py       # Abstract agent interface
│           ├── stream_agent.py # Streaming agent implementation
│           ├── factory.py    # Agent instantiation
│           └── tools/        # File ops, shell ops, web fetch, etc.
│
├── app/                      # React frontend
│   └── src/
│       ├── pages/            # Dashboard, Project, Marketplace, etc.
│       ├── components/
│       │   ├── chat/         # ChatContainer, AgentMessage
│       │   ├── panels/       # Architecture, Git, Assets, Kanban
│       │   ├── billing/      # Subscription UI
│       │   └── modals/       # CreateProject, Deployment, etc.
│       └── lib/              # API client, utilities
│
├── k8s/                      # Kubernetes manifests (Kustomize)
│   ├── base/                 # Shared base manifests
│   │   ├── kustomization.yaml
│   │   ├── namespace/        # tesslate namespace
│   │   ├── core/             # Backend, frontend, cleanup cronjob
│   │   ├── database/         # PostgreSQL deployment
│   │   ├── ingress/          # NGINX Ingress rules
│   │   ├── security/         # RBAC, network policies
│   │   ├── redis/            # Redis deployment, service, PVC
│   │   └── minio/            # S3-compatible storage (local dev)
│   ├── overlays/
│   │   ├── minikube/         # Local dev patches
│   │   │   ├── kustomization.yaml
│   │   │   ├── backend-patch.yaml   # K8S_DEVSERVER_IMAGE=local
│   │   │   ├── frontend-patch.yaml
│   │   │   └── secrets/      # Generated from .env.minikube
│   │   └── production/       # DigitalOcean patches
│   ├── scripts/              # Helper scripts
│   ├── .env.example          # Template for credentials
│   ├── .env.minikube         # Local credentials (gitignored)
│   ├── QUICKSTART.md         # Getting started guide
│   └── ARCHITECTURE.md       # Detailed K8s architecture
│
└── docker-compose.yml        # Local dev setup (Docker mode)
```

## Key Database Models (models.py)

- **User**: Auth, profile, subscription tier, theme_preset
- **Project**: Name, slug, owner, files, containers
- **ProjectSnapshot**: EBS VolumeSnapshot records for project versioning/timeline
- **Container**: Individual service in a project (frontend, backend, db)
- **ContainerConnection**: Dependencies between containers
- **Chat/Message**: Conversation history with AI
- **MarketplaceAgent**: Pre-built AI agents for purchase
- **Deployment**: External deployment records
- **DeploymentCredential**: OAuth tokens for Vercel/Netlify/etc.
- **Theme**: Customizable theme presets with colors, typography, spacing, animations
- **AgentStep**: Append-only agent execution steps (progressive persistence)
- **ExternalAPIKey**: API keys for external agent invocation (SHA-256 hashed)

## Agent Tools (orchestrator/app/agent/tools/)

| Tool | Purpose |
|------|---------|
| `read_write.py` | Read/write files in project |
| `edit.py` | Edit specific file sections |
| `bash.py` | Execute shell commands |
| `session.py` | Persistent shell sessions |
| `fetch.py` | HTTP requests for web content |
| `todos.py` | Task planning and tracking |
| `metadata.py` | Query project info |

## Documentation Knowledge Graph

The `docs/` folder contains comprehensive documentation organized as a **knowledge graph** with `CLAUDE.md` files providing context for AI agents.

### Navigating the Documentation

**Quick Start:**
1. Start at `docs/README.md` for system overview
2. Navigate to the relevant section based on your task
3. Load the `CLAUDE.md` file in that section for AI agent context
4. Follow cross-references to related contexts

**Documentation Structure:**
```
docs/
├── README.md                    # Main entry point, system overview
├── CLAUDE.md                    # Root agent context
├── architecture/                # System architecture & diagrams
│   ├── diagrams/*.mmd          # Mermaid diagrams (7 files)
│   └── CLAUDE.md               # Architecture context
├── orchestrator/                # Backend documentation
│   ├── routers/                # API endpoints
│   ├── services/               # Business logic
│   ├── agent/                  # AI agent system
│   │   └── tools/             # Agent tools
│   ├── models/                 # Database models
│   └── orchestration/          # Container management
├── app/                         # Frontend documentation
│   ├── pages/                  # Route components
│   ├── components/             # UI components
│   ├── api/                    # API client
│   ├── state/                  # State management
│   ├── contexts/               # React contexts (Auth, Command, Marketplace)
│   ├── hooks/                  # Custom hooks (useCancellable, useAuth, useTask)
│   ├── keyboard-shortcuts/     # Command palette & shortcuts system
│   └── layouts/                # Page layouts (Settings, Marketplace)
├── infrastructure/              # DevOps documentation
│   ├── kubernetes/             # K8s manifests
│   ├── docker/                 # Docker setup (dependency management, etc.)
│   └── terraform/              # AWS IaC
└── guides/                      # How-to guides
    └── theme-system.md         # Theme system complete guide
```

### Using CLAUDE.md Files

Each `CLAUDE.md` file contains:
- **Purpose**: What this system does
- **Key Files**: Source files with absolute paths
- **Related Contexts**: Links to other CLAUDE.md files
- **Quick Reference**: Common patterns and gotchas
- **When to Load**: Conditions for loading this context

**Best Practices:**
1. Load the most specific CLAUDE.md first (e.g., `docs/orchestrator/agent/tools/CLAUDE.md` for agent tools)
2. Follow "Related Contexts" links when you need broader understanding
3. Reference diagram files in `docs/architecture/diagrams/` for visual architecture
4. Use the README.md files for comprehensive documentation, CLAUDE.md for quick context

### Key Entry Points by Task

| Task | Start Here |
|------|------------|
| Docker setup from scratch | `docs/guides/docker-setup.md` |
| Database seeding | `CLAUDE.md` → "Database Seeding" section (this file) |
| Database migrations | `docs/guides/database-migrations.md` |
| Understanding system architecture | `docs/architecture/CLAUDE.md` |
| Backend API development | `docs/orchestrator/routers/CLAUDE.md` |
| AI agent development | `docs/orchestrator/agent/CLAUDE.md` |
| Frontend development | `docs/app/CLAUDE.md` |
| Container orchestration | `docs/orchestrator/orchestration/CLAUDE.md` |
| Kubernetes deployment | `docs/infrastructure/kubernetes/CLAUDE.md` |
| Database models | `docs/orchestrator/models/CLAUDE.md` |
| Payment integration | `docs/orchestrator/services/stripe.md` |
| Theme system | `docs/guides/theme-system.md` |
| Keyboard shortcuts & commands | `docs/app/keyboard-shortcuts/CLAUDE.md` |
| Settings pages | `docs/app/pages/settings.md` |
| Marketplace pages | `docs/app/pages/marketplace-browse.md` |
| Page layouts | `docs/app/layouts/CLAUDE.md` |
| Real-time agent architecture | `docs/guides/real-time-agent-architecture.md` |
| External agent API | `docs/orchestrator/routers/external-agent.md` |
| Redis/pub-sub infrastructure | `docs/orchestrator/services/pubsub.md` |
| Worker system | `docs/orchestrator/services/worker.md` |

## Deployment Modes

### Docker (Local Dev)
- `DEPLOYMENT_MODE=docker` in config
- Traefik routes `*.localhost` to containers
- Project files on local filesystem

**For complete Docker setup from scratch, see: [docs/guides/docker-setup.md](docs/guides/docker-setup.md)**

#### Docker Quick Start
```bash
cp .env.example .env           # configure SECRET_KEY, LITELLM_API_BASE, LITELLM_MASTER_KEY
docker compose up --build -d   # build images and start all services
docker compose ps              # verify all 4 services are healthy
# Services started: app (frontend), orchestrator (backend), postgres, traefik, redis, worker
# Access: http://localhost (frontend), http://localhost:8000/docs (API docs)

# IMPORTANT: Build devserver image (required for user project containers)
docker build -t tesslate-devserver:latest -f orchestrator/Dockerfile.devserver orchestrator/
```

#### Docker Clean Slate Reset
```bash
docker compose down --volumes --remove-orphans
docker images --format "{{.Repository}}:{{.Tag}} {{.ID}}" | grep -i tesslate | awk '{print $2}' | sort -u | xargs docker rmi -f
docker compose up --build -d
```

### Database Seeding

Seeds marketplace bases, agents, open-source agents, and themes. **Required after first setup or clean slate reset.**

Scripts are in `scripts/seed/` and are idempotent (safe to re-run).

#### Seed All (Docker Compose)
```bash
# 1. Run migrations first
docker exec tesslate-orchestrator alembic upgrade head

# 2. Copy seed scripts into container
docker cp scripts/seed/seed_marketplace_bases.py tesslate-orchestrator:/tmp/
docker cp scripts/seed/seed_marketplace_agents.py tesslate-orchestrator:/tmp/
docker cp scripts/seed/seed_opensource_agents.py tesslate-orchestrator:/tmp/
docker cp scripts/seed/seed_themes.py tesslate-orchestrator:/tmp/
docker cp scripts/seed/seed_community_bases.py tesslate-orchestrator:/tmp/

# 3. Copy theme JSON files
docker exec tesslate-orchestrator mkdir -p /tmp/themes
docker cp scripts/themes/. tesslate-orchestrator:/tmp/themes/

# 4. Run seed scripts (order matters: bases first, then agents)
# On Windows, prefix each command with MSYS_NO_PATHCONV=1
docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed_marketplace_bases.py
docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed_marketplace_agents.py
docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed_opensource_agents.py
# Themes script needs themes_dir override since it's not in its expected relative path:
docker exec -e PYTHONPATH=/app tesslate-orchestrator python -c "
import asyncio, sys; sys.path.insert(0, '/app')
from pathlib import Path
exec(open('/tmp/seed_themes.py').read().split('if __name__')[0])
asyncio.run(seed_themes(themes_dir=Path('/tmp/themes')))
"
# Community bases (open-source project templates)
docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed_community_bases.py
```

#### Seed All (Kubernetes)
```bash
# Get pod name
POD=$(kubectl get pod -n tesslate -l app=tesslate-backend -o jsonpath='{.items[0].metadata.name}')

# Copy scripts
kubectl cp scripts/seed/seed_marketplace_bases.py tesslate/$POD:/tmp/
kubectl cp scripts/seed/seed_marketplace_agents.py tesslate/$POD:/tmp/
kubectl cp scripts/seed/seed_opensource_agents.py tesslate/$POD:/tmp/
kubectl cp scripts/seed/seed_themes.py tesslate/$POD:/tmp/
kubectl cp scripts/seed/seed_community_bases.py tesslate/$POD:/tmp/
kubectl cp scripts/themes tesslate/$POD:/tmp/themes

# Run (on Windows prefix with MSYS_NO_PATHCONV=1)
kubectl exec -n tesslate $POD -- python /tmp/seed_marketplace_bases.py
kubectl exec -n tesslate $POD -- python /tmp/seed_marketplace_agents.py
kubectl exec -n tesslate $POD -- python /tmp/seed_opensource_agents.py
kubectl exec -n tesslate $POD -- python -c "
import asyncio, sys; sys.path.insert(0, '/app')
from pathlib import Path
exec(open('/tmp/seed_themes.py').read().split('if __name__')[0])
asyncio.run(seed_themes(themes_dir=Path('/tmp/themes')))
"
kubectl exec -n tesslate $POD -- python /tmp/seed_community_bases.py
```

#### What Gets Seeded

| Script | Data | Count |
|--------|------|-------|
| `seed_marketplace_bases.py` | Project templates (Next.js 16, Vite+React+FastAPI, Vite+React+Go, Expo) | 4 |
| `seed_marketplace_agents.py` | Official agents + Tesslate account (Stream Builder, Tesslate Agent, React Component Builder, API Integration, ReAct Agent) | 5 |
| `seed_opensource_agents.py` | Community agents (Code Analyzer, Doc Writer, Refactoring Assistant, Test Generator, API Designer, DB Schema Designer) | 6 |
| `seed_themes.py` | UI themes (default-dark, default-light, midnight, ocean, forest, rose, sunset) | 7 |
| `seed_community_bases.py` | Community open-source bases (Go, Rust, Django, Laravel, Rails, Flutter, .NET, etc.) | 63 |

### Kubernetes (Minikube/Production)
- `DEPLOYMENT_MODE=kubernetes` in config
- Per-project namespaces (`proj-{uuid}`) with NetworkPolicy isolation
- EBS VolumeSnapshots for project persistence and versioning
- NGINX Ingress for routing
- Pod affinity for multi-container projects (same node)

#### EBS VolumeSnapshot Pattern
User project containers use persistent EBS block storage with snapshot-based versioning:
1. **Storage**: Persistent EBS volumes (gp3) that survive pod restarts - no data loss
2. **Snapshots**: Created on hibernation or manually via Timeline UI (non-blocking)
3. **Restore**: PVC created from snapshot on project start (lazy-loading, near-instant)
4. **Timeline**: Up to 5 snapshots per project for version history and restore points

#### Key K8s Config Settings (config.py)
```python
k8s_devserver_image: str           # Image for user containers (tesslate-devserver:latest)
k8s_image_pull_secret: str         # Registry secret (empty for local images)
k8s_storage_class: str             # StorageClass for PVCs (tesslate-block-storage)
k8s_snapshot_class: str            # VolumeSnapshotClass (tesslate-ebs-snapshots)
k8s_snapshot_retention_days: int   # Days to keep soft-deleted snapshots (30)
k8s_max_snapshots_per_project: int # Max snapshots in timeline (5)
k8s_enable_pod_affinity: bool      # Keep multi-container projects on same node
redis_url: str                     # Redis connection string (empty = in-memory fallback)
worker_max_jobs: int               # Concurrent agent tasks per worker pod (10)
worker_job_timeout: int            # Task timeout in seconds (600)
```

#### Minikube vs Production Config
| Setting | Minikube | Production (AWS EKS) |
|---------|----------|----------------------|
| `K8S_DEVSERVER_IMAGE` | `tesslate-devserver:latest` | `<ECR_REGISTRY>/tesslate-devserver:latest` |
| `K8S_IMAGE_PULL_SECRET` | `` (empty) | `ecr-credentials` |
| `K8S_WILDCARD_TLS_SECRET` | `` (empty, use HTTP) | `tesslate-wildcard-tls` (use HTTPS) |
| `K8S_SNAPSHOT_CLASS` | `tesslate-btrfs-snapshots` (via btrfs-CSI) | `tesslate-ebs-snapshots` |

#### Minikube Limitations
- **HTTP only**: No TLS certificates, all URLs use `http://`
- **Data persistence**: PVCs persist across restarts, but data is lost if cluster is deleted

**For complete minikube setup instructions, see: [docs/guides/minikube-setup.md](docs/guides/minikube-setup.md)**

## Minikube Local Development (Windows)

### CRITICAL: Image Update Workflow

**Problem**: `minikube image load` does NOT overwrite existing images with the same tag. This causes code changes to not deploy even after rebuilding.

**Solution**: Always delete old images before loading new ones.

### Complete Build & Deploy Workflow

```powershell
# 1. Delete old image from minikube's Docker daemon
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest

# 2. Delete local image and rebuild with --no-cache
docker rmi -f tesslate-backend:latest
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/

# 3. Load new image to minikube
minikube -p tesslate image load tesslate-backend:latest

# 4. Force pod restart (rollout restart may use cached image)
kubectl delete pod -n tesslate -l app=tesslate-backend

# 5. Wait for new pod to be ready
kubectl rollout status deployment/tesslate-backend -n tesslate --timeout=120s

# 6. Verify fix is deployed (check specific code)
kubectl exec -n tesslate deployment/tesslate-backend -- grep "project-source" /app/app/services/orchestration/kubernetes/helpers.py
```

### Quick Reference Commands

```powershell
# Start minikube cluster
minikube start -p tesslate --driver=docker --memory=4096 --cpus=2
minikube -p tesslate addons enable ingress

# Start tunnel (run in separate terminal, keep it open)
minikube -p tesslate tunnel

# Port-forward for local access
kubectl port-forward -n tesslate svc/tesslate-frontend-service 5000:80
kubectl port-forward -n tesslate svc/tesslate-backend-service 8000:8000

# Check what images are in minikube
minikube -p tesslate ssh -- docker images | grep tesslate

# View pod logs
kubectl logs -f deployment/tesslate-backend -n tesslate
kubectl logs -f deployment/tesslate-frontend -n tesslate

# Deploy all manifests
kubectl apply -k k8s/overlays/minikube
```

### Building All Images

```powershell
# Backend
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest
docker rmi -f tesslate-backend:latest
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
minikube -p tesslate image load tesslate-backend:latest
kubectl delete pod -n tesslate -l app=tesslate-backend

# Frontend
minikube -p tesslate ssh -- docker rmi -f tesslate-frontend:latest
docker rmi -f tesslate-frontend:latest
docker build --no-cache -t tesslate-frontend:latest -f app/Dockerfile.prod app/
minikube -p tesslate image load tesslate-frontend:latest
kubectl delete pod -n tesslate -l app=tesslate-frontend

# Devserver (for user project containers)
# NOTE: Dockerfile is in orchestrator/ not devserver/
minikube -p tesslate ssh -- docker rmi -f tesslate-devserver:latest
docker rmi -f tesslate-devserver:latest
docker build --no-cache -t tesslate-devserver:latest -f orchestrator/Dockerfile.devserver orchestrator/
minikube -p tesslate image load tesslate-devserver:latest
```

### Common Issues & Fixes

**Image not updating after rebuild:**
```powershell
# The image is cached in minikube. Delete it first:
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest
# Then rebuild and load (see workflow above)
```

**Pod stuck in ImagePullBackOff:**
```powershell
# Image not loaded into minikube
minikube -p tesslate image load tesslate-backend:latest
kubectl delete pod -n tesslate -l app=tesslate-backend
```

**Tunnel not working:**
```powershell
# Run tunnel in admin PowerShell
minikube -p tesslate tunnel
# Or use port-forward instead
kubectl port-forward -n tesslate svc/tesslate-frontend-service 5000:80
```

**NGINX configuration-snippet annotation blocked:**
```
# Minikube's NGINX Ingress has configuration-snippet disabled by default
# Use proxy-hide-header annotation instead (already fixed in kubernetes_orchestrator.py)
```

**User container ImagePullBackOff:**
```powershell
# Check which image is being used
kubectl describe pod -n proj-<uuid> | grep Image

# Check K8S_DEVSERVER_IMAGE env var:
kubectl exec -n tesslate deployment/tesslate-backend -- env | grep K8S_DEVSERVER

# Should be: K8S_DEVSERVER_IMAGE=tesslate-devserver:latest
# This is set in k8s/overlays/minikube/backend-patch.yaml
```

**User container 503 error / page not loading:**
```powershell
# Check if pod is running
kubectl get pods -n proj-<project-uuid>

# Check pod events
kubectl describe pod -n proj-<project-uuid>

# Check dev server logs
kubectl logs -n proj-<uuid> <pod-name> -c dev-server

# Check if PVC is bound
kubectl get pvc -n proj-<project-uuid>
```

**Volume name mismatch error:**
```
# Error: volumeMounts[0].name: Not found: "project-data"
# Fix: Volume names should be "project-source" not "project-data"
# This was fixed in kubernetes/helpers.py
```


## AWS EKS Production Deployment

### Infrastructure

- **Region**: us-east-1
- **Cluster**: <EKS_CLUSTER_NAME>
- **Domain**: your-domain.com (Cloudflare DNS)
- **ECR Registry**: <ECR_REGISTRY>
- **EBS Storage**: gp3 volumes with VolumeSnapshot support for project persistence
- **AWS User**: Always use `<AWS_IAM_USER>` credentials for deployments

### Terraform Deployment & Configuration

Terraform manages AWS infrastructure with environment-specific state files and variables.

**Backend Configuration (Multi-Environment Support):**
```bash
# Production and beta use SEPARATE state files in same S3 bucket:
# - production: s3://<TERRAFORM_STATE_BUCKET>/production/terraform.tfstate
# - beta:       s3://<TERRAFORM_STATE_BUCKET>/beta/terraform.tfstate

# Use aws-deploy.sh helper script for all terraform operations:
./scripts/aws-deploy.sh init production     # Initialize with production backend
./scripts/aws-deploy.sh plan production     # Plan changes
./scripts/aws-deploy.sh apply production    # Apply changes (requires confirmation)
./scripts/aws-deploy.sh destroy production  # Destroy infrastructure (requires typing "destroy production")

# For beta environment:
./scripts/aws-deploy.sh init beta
./scripts/aws-deploy.sh plan beta
./scripts/aws-deploy.sh apply beta
```

**Shared ECR Stack:**

ECR repositories (`tesslate-backend`, `tesslate-frontend`, `tesslate-devserver`) are shared across environments — both push different image tags (`:beta`, `:production`) to the same repos. To prevent state conflicts, ECR is managed by a **dedicated shared stack** (`k8s/terraform/shared/`) with its own state file. Environment stacks reference ECR via computed URL locals.

```bash
# Manage shared ECR resources
./scripts/aws-deploy.sh init shared
./scripts/aws-deploy.sh plan shared
./scripts/aws-deploy.sh apply shared
```

**Terraform Secrets Management:**

Terraform tfvars files are stored in **AWS Secrets Manager** (as raw content) and must be downloaded manually before running Terraform. This enables secure team collaboration.

**Key Features:**
- Manual tfvars management - download when needed
- No secrets in git (tfvars files are in `.gitignore`)
- Centralized storage - team downloads from AWS instead of manual sharing
- Simple workflow - download once, use with standard terraform `-var-file`

**Download tfvars** (required before first terraform run):
```bash
# View tfvars content from AWS (default, no local file created)
./scripts/terraform/secrets.sh production

# Download tfvars from AWS to local file
./scripts/terraform/secrets.sh download production

# This creates: k8s/terraform/aws/terraform.production.tfvars
```

**Run terraform** (after downloading):
```bash
# Now terraform commands work
./scripts/aws-deploy.sh plan production
./scripts/aws-deploy.sh apply production
```

**Initial upload** (one-time setup):
```bash
# Upload existing terraform.{env}.tfvars to AWS
./scripts/terraform/secrets.sh upload production
./scripts/terraform/secrets.sh upload beta

# Test viewing
./scripts/terraform/secrets.sh production

# Team members can now download and use
# ./scripts/terraform/secrets.sh download production
```

**Updating secrets**:
```bash
# 1. Download latest (to avoid conflicts)
./scripts/terraform/secrets.sh download production

# 2. Edit local file
vim k8s/terraform/aws/terraform.production.tfvars

# 3. Upload to AWS
./scripts/terraform/secrets.sh upload production

# 4. Notify team to re-download: ./scripts/terraform/secrets.sh download production
```

**View secrets in AWS**:
```bash
# View tfvars content from AWS (this is the default)
./scripts/terraform/secrets.sh production
# or explicit: ./scripts/terraform/secrets.sh view production
```

**AWS Secrets Manager Structure:**
- `tesslate/terraform/production` - Raw content of terraform.production.tfvars
- `tesslate/terraform/beta` - Raw content of terraform.beta.tfvars

**Required IAM Permissions:**
- `secretsmanager:GetSecretValue`
- `secretsmanager:PutSecretValue`
- `secretsmanager:CreateSecret`
- `secretsmanager:DescribeSecret`

See [scripts/terraform/README.md](scripts/terraform/README.md) for full documentation.

### Initial Setup / Login

```powershell
# Configure kubectl for EKS cluster
aws eks update-kubeconfig --region us-east-1 --name <EKS_CLUSTER_NAME>

# Verify connection
kubectl get nodes
kubectl get pods -n tesslate
```

### Build & Deploy Images (Recommended)

Use `aws-deploy.sh build` to build, push to ECR, and restart pods in one command.

```bash
# Build all images (backend, frontend, devserver)
./scripts/aws-deploy.sh build beta
./scripts/aws-deploy.sh build production

# Build specific image(s)
./scripts/aws-deploy.sh build production backend
./scripts/aws-deploy.sh build beta frontend backend

# What it does: ECR login → docker build --no-cache → push → delete pod → wait for rollout → verify
```

### Deploy / Restart Pods

```powershell
# Restart backend to pick up new image
kubectl rollout restart deployment/tesslate-backend -n tesslate
kubectl rollout status deployment/tesslate-backend -n tesslate --timeout=120s

# Restart frontend
kubectl rollout restart deployment/tesslate-frontend -n tesslate
kubectl rollout status deployment/tesslate-frontend -n tesslate --timeout=120s

# IMPORTANT: Restart ingress controller to refresh endpoint routing
# This prevents site loading issues after backend restarts
kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=120s

# Apply all manifests with images from terraform (recommended)
./scripts/aws-deploy.sh deploy-k8s beta        # for beta
./scripts/aws-deploy.sh deploy-k8s production  # for production
```

### Debugging Commands

```powershell
# Check pod status
kubectl get pods -n tesslate -o wide
kubectl get pods --all-namespaces | grep proj-

# Check logs
kubectl logs -n tesslate deployment/tesslate-backend --tail=100
kubectl logs -n tesslate deployment/tesslate-backend -f  # follow

# Check ingress
kubectl get ingress -n tesslate
kubectl get ingress --all-namespaces | grep proj-

# Check NGINX ingress controller logs
kubectl logs -n ingress-nginx deployment/ingress-nginx-controller --tail=50

# Check certificates
kubectl get certificate -n tesslate
kubectl describe certificate tesslate-wildcard-tls -n tesslate

# Execute commands in backend pod (use MSYS_NO_PATHCONV=1 on Windows)
MSYS_NO_PATHCONV=1 kubectl exec -n tesslate deployment/tesslate-backend -- cat /app/app/config.py
MSYS_NO_PATHCONV=1 kubectl exec -n tesslate deployment/tesslate-backend -- python -c "print('hello')"

# Check user project pods
kubectl get pods -n proj-<project-uuid>
kubectl logs -n proj-<project-uuid> <pod-name> -c dev-server
kubectl get pvc -n proj-<project-uuid>  # Check storage

# Resource usage
kubectl top pods -n tesslate
kubectl top nodes
```

### Cleanup Orphaned Project Namespaces

```powershell
# List orphaned project namespaces
kubectl get ns | grep proj-

# Delete orphaned namespace (cascades to all resources)
kubectl delete ns proj-<project-uuid>
```

### Secrets Management

```powershell
# View secrets (base64 encoded)
kubectl get secret tesslate-secrets -n tesslate -o yaml

# Update a secret value
kubectl create secret generic tesslate-secrets -n tesslate \
  --from-literal=SECRET_KEY=xxx \
  --from-literal=DATABASE_URL=xxx \
  --dry-run=client -o yaml | kubectl apply -f -
```

### AWS EKS Config Settings (k8s/overlays/aws-base/backend-patch.yaml)

| Setting | Beta | Production |
|---------|------|------------|
| `K8S_DEVSERVER_IMAGE` | `...tesslate-devserver:beta` | `...tesslate-devserver:production` |
| `K8S_IMAGE_PULL_SECRET` | `""` | `""` |
| `APP_DOMAIN` | `your-domain.com` | `opensail.tesslate.com` |
| `COOKIE_DOMAIN` | `.your-domain.com` | `.opensail.tesslate.com` |
| `replicas` | `1` (single replica - tasks stored in-memory) | `1` |

### AWS Overlay: envFrom Auto-Sync Architecture

The AWS backend overlay (`k8s/overlays/aws-base/backend-patch.yaml`) uses a two-part strategy:

1. **`envFrom`** — auto-mounts ALL keys from 3 terraform-managed secrets (`tesslate-app-secrets`, `postgres-secret`, `s3-credentials`). Adding a new key in terraform's `kubernetes.tf` automatically makes it available in the pod — **no manual kustomize sync needed**.

2. **`env` with `$patch: replace`** — replaces the base manifest's env array with ONLY static values (not in any secret) and 1 alias mapping (`K8S_INGRESS_DOMAIN` → `APP_DOMAIN`). The `$patch: replace` prevents stale base entries from merging in.

**When adding new config:**
- **Secret-based values** (domain, API keys, OAuth, etc.): Add to terraform `kubernetes.tf` secrets → automatically picked up via `envFrom`
- **Static values** (feature flags, class names, etc.): Add to `backend-patch.yaml` env array

### Frontend Config: API_URL Must NOT Include `/api`

The frontend `api-url` in the `frontend-config` ConfigMap (managed by terraform `kubernetes.tf`) must be the **base domain only** (e.g., `https://opensail.tesslate.com`), NOT `https://opensail.tesslate.com/api`. All API calls in `app/src/lib/api.ts` already include the `/api` prefix in their paths, so including `/api` in the base URL causes double `/api/api/` paths.

### Common AWS Issues & Fixes

**Container start fails with WebSocket error:**
```
WebSocketBadStatusException: Handshake status 200 OK
```
This is a bug in kubernetes Python client v34.x where REST calls get routed through WebSocket.
Workaround: Pin kubernetes client to <32.0.0 in pyproject.toml, or wait for upstream fix.

**SSL certificate doesn't cover subdomains:**
```
ERR_CERT_AUTHORITY_INVALID for foo.bar.your-domain.com
```
Wildcard certs (*.your-domain.com) only cover ONE level of subdomain.
Fix: Enable Cloudflare proxy (orange cloud) with SSL mode "Full", or change URL structure.

**Orphaned namespaces causing slowness:**
When projects are deleted but K8s namespaces aren't cleaned up, NGINX Ingress Controller
repeatedly tries to resolve them, causing configuration reload loops.
Fix: The `delete_project_namespace()` method was added to properly clean up on project deletion.

**ECR credentials expired:**
```powershell
# Re-login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com
```

**Cloudflare certificate not issued:**
```powershell
# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager --tail=50

# Check certificate status
kubectl describe certificate tesslate-wildcard-tls -n tesslate

# Cloudflare API token needs Zone:Zone:Read and Zone:DNS:Edit permissions
```
