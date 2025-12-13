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
│       │   ├── kubernetes_orchestrator.py      # K8s container mgmt
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
├── k8s/                      # Kubernetes manifests
│   ├── manifests/
│   │   ├── core/             # Backend, frontend deployments
│   │   ├── database/         # PostgreSQL StatefulSet
│   │   └── ingress/          # NGINX Ingress rules
│   └── scripts/deployment/   # Build, push, deploy scripts
│
└── docker-compose.yml        # Local dev setup
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

### Kubernetes (Production)
- `DEPLOYMENT_MODE=kubernetes` in config
- Per-project namespaces with NetworkPolicy isolation
- Shared PVC with subPath per project
- NGINX Ingress for routing
- S3 storage for project hibernation

---

## DigitalOcean Kubernetes Cluster (NYC2)

### Cluster Information
- **Cluster Name:** tesslate-studio-nyc2
- **Cluster ID:** 4ddf2adb-b176-4d14-8198-92b9c28b9461
- **Region:** NYC2
- **Registry:** registry.digitalocean.com/tesslate-container-registry-nyc3
- **Kubernetes Version:** 1.34.1-do.0
- **Nodes:** 2 nodes (pool-55m290s1r)

### Quick Access Commands

```bash
# Authenticate with DigitalOcean
doctl auth switch tesslate

# Connect to cluster
doctl kubernetes cluster kubeconfig save tesslate-studio-nyc2

# Verify connection
kubectl cluster-info
kubectl get nodes

# View all resources
kubectl get all -n tesslate

# Common troubleshooting
kubectl get pods -n tesslate -w
kubectl logs -f deployment/tesslate-backend -n tesslate
kubectl logs -f deployment/tesslate-frontend -n tesslate
kubectl describe pod <pod-name> -n tesslate

# Check ingress and SSL
kubectl get ingress -n tesslate
kubectl get certificates -n tesslate

# Scale/restart deployments
kubectl scale deployment tesslate-backend --replicas=3 -n tesslate
kubectl rollout restart deployment/tesslate-backend -n tesslate

# Database backup
kubectl exec -n tesslate deployment/postgres -- \
  pg_dump -U tesslate_user tesslate > backup-$(date +%Y%m%d).sql
```

### Deployment Commands

```bash
# Generate secrets (first time only)
cd k8s && bash generate-secrets.sh

# Deploy application
cd k8s/scripts/deployment
./deploy-all.sh

# Or individual steps:
./install-prerequisites.sh        # NGINX Ingress, cert-manager
./setup-registry-auth.sh          # Container registry auth
./build-push-images.sh            # Build and push images
./deploy-application.sh           # Deploy app
./deploy-user-namespace.sh        # Setup user environments
```

### Testing Commands

```bash
# Test registry auth
doctl registry login
docker pull registry.digitalocean.com/tesslate-container-registry-nyc3/tesslate-backend:latest

# Test secrets
kubectl get secrets -n tesslate
kubectl describe secret tesslate-app-secrets -n tesslate

# Test database
kubectl exec -it deployment/postgres -n tesslate -- psql -U tesslate_user -d tesslate

# Port-forward for local testing
kubectl port-forward -n tesslate svc/tesslate-backend-service 8005:8005
kubectl port-forward -n tesslate svc/tesslate-frontend-service 8080:80
```

### Monitoring & Debugging

```bash
# Resource usage
kubectl top nodes
kubectl top pods -n tesslate

# Recent events
kubectl get events -n tesslate --sort-by='.lastTimestamp'

# Cert-manager issues
kubectl logs -n cert-manager deployment/cert-manager
kubectl get challenges -A

# NGINX ingress logs
kubectl logs -n ingress-nginx deployment/ingress-nginx-controller

# Shell into pods
kubectl exec -it deployment/tesslate-backend -n tesslate -- /bin/bash
```

### Common Issues & Fixes

**Pods not starting:**
```bash
kubectl describe pod <pod-name> -n tesslate
kubectl logs <pod-name> -n tesslate
```

**Image pull errors:**
```bash
cd k8s/scripts/deployment && ./setup-registry-auth.sh
```

**Certificate not ready:**
```bash
kubectl describe certificate tesslate-domain-cert -n tesslate
kubectl logs -n cert-manager deployment/cert-manager
```

**Database connection failed:**
```bash
kubectl logs deployment/postgres -n tesslate
kubectl get secret postgres-secret -n tesslate -o yaml
```
