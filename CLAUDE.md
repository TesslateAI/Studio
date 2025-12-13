You are a senior level coding agent. You will apply real world solutions to all the problems, fixing them in such a way where you do not cheat the solution, break existing functionality, and are scoped in. The solutions you write must be scalable and for the future, not fixing or hardcoding.

CRITICAL -- ENSURE ALL CHANGES ARE NON-BLOCKING

Everything u do or write should be non-blocking so certain actions don't hold up other people on our software. 

# Tesslate Studio

When I have an issue, fix it for the next time it happens in a general, scalable way. For example, if a container fails on startup, ensure all future container startups work 100%.

## What is Tesslate Studio?

AI-powered web application builder that lets users create, edit, deploy, and manage full-stack apps using natural language. Users describe what they want, an AI agent writes the code, and the platform handles containerized deployment.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Tesslate Studio                          │
├─────────────────────────────────────────────────────────────┤
│  Frontend (app/)           │   Orchestrator (orchestrator/) │
│  React + Vite + TypeScript │   FastAPI + Python             │
│  - Monaco Editor           │   - Auth (JWT/OAuth)           │
│  - Live Preview            │   - Project Management         │
│  - Chat UI                 │   - AI Agent System            │
│  - File Browser            │   - Container Orchestration    │
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
POST /api/chat/stream → routers/chat.py
  ├─> create_agent_from_db_model() → agent/factory.py
  │     └─> Instantiate agent with tools + system prompt
  ├─> agent.run(user_request, context) → agent/stream_agent.py
  │     ├─ LLM call with system prompt + tools
  │     ├─ Tool execution loop (write files, run commands, etc.)
  │     └─ Yield streaming events to client
  └─> Client renders agent steps in real-time
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
      └─> URLs: {container}.studio-test.tesslate.com
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
│       │   └── ...
│       ├── services/
│       │   ├── docker_compose_orchestrator.py  # Docker container mgmt
│       │   ├── orchestration/
│       │   │   ├── kubernetes_orchestrator.py  # K8s container mgmt
│       │   │   └── kubernetes/
│       │   │       ├── client.py               # K8s API client wrapper
│       │   │       └── helpers.py              # Deployment manifests, S3 init
│       │   ├── s3_manager.py                   # S3 Sandwich hydration/dehydration
│       │   ├── litellm_service.py              # AI model routing
│       │   └── ...
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

- **User**: Auth, profile, subscription tier
- **Project**: Name, slug, owner, files, containers
- **Container**: Individual service in a project (frontend, backend, db)
- **ContainerConnection**: Dependencies between containers
- **Chat/Message**: Conversation history with AI
- **MarketplaceAgent**: Pre-built AI agents for purchase
- **Deployment**: External deployment records
- **DeploymentCredential**: OAuth tokens for Vercel/Netlify/etc.

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

## Deployment Modes

### Docker (Local Dev)
- `DEPLOYMENT_MODE=docker` in config
- Traefik routes `*.localhost` to containers
- Project files on local filesystem

### Kubernetes (Minikube/Production)
- `DEPLOYMENT_MODE=kubernetes` in config
- Per-project namespaces (`proj-{uuid}`) with NetworkPolicy isolation
- S3 Sandwich pattern: Ephemeral PVC + S3 for persistence
- NGINX Ingress for routing
- Pod affinity for multi-container projects (same node)

#### S3 Sandwich Pattern
User project containers use ephemeral block storage with S3 persistence:
1. **Hydration**: Init container downloads project from S3 (if exists) or uses template
2. **Runtime**: Fast local I/O on PVC for file edits, npm install, etc.
3. **Dehydration**: PreStop hook uploads project to S3 before pod termination

#### Key K8s Config Settings (config.py)
```python
k8s_devserver_image: str      # Image for user containers (tesslate-devserver:latest)
k8s_image_pull_secret: str    # Registry secret (empty for local images)
k8s_use_s3_storage: bool      # Enable S3 Sandwich pattern (default: True)
k8s_storage_class: str        # StorageClass for PVCs (tesslate-block-storage)
k8s_enable_pod_affinity: bool # Keep multi-container projects on same node
```

#### Minikube vs Production Config
| Setting | Minikube | Production (DO) |
|---------|----------|-----------------|
| `K8S_DEVSERVER_IMAGE` | `tesslate-devserver:latest` | `registry.digitalocean.com/.../tesslate-devserver:latest` |
| `K8S_IMAGE_PULL_SECRET` | `` (empty) | `tesslate-container-registry-nyc3` |
| `S3_ENDPOINT_URL` | `http://minio.minio-system.svc.cluster.local:9000` | `https://nyc3.digitaloceanspaces.com` |


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

# Check init container logs (hydration)
kubectl logs -n proj-<uuid> <pod-name> -c hydrate-project

# Check dev server logs
kubectl logs -n proj-<uuid> <pod-name> -c dev-server
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
- **S3 Bucket**: tesslate-project-storage-prod (for project files)

### Initial Setup / Login

```powershell
# Configure kubectl for EKS cluster
aws eks update-kubeconfig --region us-east-1 --name <EKS_CLUSTER_NAME>

# Verify connection
kubectl get nodes
kubectl get pods -n tesslate
```

### ECR Login & Image Push

```powershell
# Login to ECR (required before push)
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <ECR_REGISTRY>

# Build, tag, and push backend
docker build -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
docker tag tesslate-backend:latest <ECR_REGISTRY>/tesslate-backend:latest
docker push <ECR_REGISTRY>/tesslate-backend:latest

# Build, tag, and push frontend
docker build -t tesslate-frontend:latest -f app/Dockerfile.prod app/
docker tag tesslate-frontend:latest <ECR_REGISTRY>/tesslate-frontend:latest
docker push <ECR_REGISTRY>/tesslate-frontend:latest

# Build, tag, and push devserver (user project containers)
docker build -t tesslate-devserver:latest -f orchestrator/Dockerfile.devserver orchestrator/
docker tag tesslate-devserver:latest <ECR_REGISTRY>/tesslate-devserver:latest
docker push <ECR_REGISTRY>/tesslate-devserver:latest
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

# Apply all manifests (if changed)
kubectl apply -k k8s/overlays/aws
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
kubectl logs -n proj-<project-uuid> <pod-name> -c hydrate-project  # init container

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

### AWS EKS Config Settings (k8s/overlays/aws/backend-patch.yaml)

| Setting | Value |
|---------|-------|
| `K8S_DEVSERVER_IMAGE` | `<ECR_REGISTRY>/tesslate-devserver:latest` |
| `K8S_IMAGE_PULL_SECRET` | `ecr-credentials` |
| `S3_ENDPOINT_URL` | `https://s3.us-east-1.amazonaws.com` |
| `S3_BUCKET_NAME` | `tesslate-project-storage-prod` |
| `COOKIE_DOMAIN` | `.your-domain.com` |
| `replicas` | `1` (single replica - tasks stored in-memory) |

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
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <ECR_REGISTRY>
```

**Cloudflare certificate not issued:**
```powershell
# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager --tail=50

# Check certificate status
kubectl describe certificate tesslate-wildcard-tls -n tesslate

# Cloudflare API token needs Zone:Zone:Read and Zone:DNS:Edit permissions
```
