You are a senior level coding agent. You will apply real world solutions to all the problems, fixing them in such a way where you do not cheat the solution, break existing functionality, and are scoped in. The solutions you write must be scalable and for the future, not fixing or hardcoding.

Always read through the docs/ to find items it is a knowledgegraph

Use subagents generously if you are doing bulk task items that have a small / atomic scope. 

don't do conditional logic for k8s and docker implementation differences. try to keep it as similar as possible unless if a platform requires differeces. Prioritize the k8s (keep that logic more intact than docker. )

On windows use MSYS_NO_PATHCONV=1 while running kubectl or docker exec commands. 
The ECR IS <AWS_ACCOUNT_ID> not <AWS_ACCOUNT_ID>

CRITICAL -- ENSURE ALL CHANGES ARE NON-BLOCKING

Everything u do or write should be non-blocking so certain actions don't hold up other people on our software.

## Commit Messages

**BANNED:** Writing commit messages that describe the development flow (what you added/removed during the session). A commit message is about the final diff state — what a reader of `git show` would see.

**BANNED:** Writing commit messages that only describe YOUR changes when the staged diff includes OTHER pre-staged files. Always `git diff --cached --stat` and inspect ALL files in the diff before writing the message. The message must cover every file in the commit, not just the ones you touched in this session.

**Good pattern:** Describe the net effect. If you added something and removed something else in the same commit, only mention what's in the final diff.
**Bad pattern:** "Remove fast path from X" when the fast path was added and removed in the same commit — it never existed from the diff's perspective.

```
# BANNED - describes development steps, not the diff
feat: add fast path, then remove it, refactor health check

# BANNED - only describes your changes, ignores pre-staged files
feat: fix loading screen colors
# (when the staged diff also includes bash tool changes, health checks, etc.)

# GOOD - describes what the FULL diff actually contains
feat: add compute manager with quota enforcement and container-id status lookup
```

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

### 1b. Universal Project Setup (setup-config)
```
POST /api/projects/{id}/setup-config → routers/projects.py
  ├─> Read .tesslate/config.json from project
  ├─> Parse containers, startup commands, connections
  ├─> Create/update Container models from config
  └─> Return structured project configuration

The Librarian agent analyzes a project and generates .tesslate/config.json,
which defines containers, startup_command, connections, and metadata.
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
│       │   ├── projects.py   # Project CRUD, start/stop containers, setup-config
│       │   ├── chat.py       # Agent chat, streaming responses
│       │   ├── billing.py    # Stripe subscriptions
│       │   ├── deployments.py # Vercel/Netlify/Cloudflare
│       │   ├── git.py        # Git operations
│       │   ├── external_agent.py # External agent API (API keys, SSE, webhooks)
│       │   ├── channels.py   # Messaging channel configuration (Telegram, Slack, Discord, WhatsApp)
│       │   ├── mcp.py        # User MCP server management
│       │   ├── mcp_server.py # MCP server marketplace catalog
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
│       │   ├── skill_discovery.py          # Skill discovery and loading for agents
│       │   ├── channels/                   # Messaging channel integrations
│       │   │   ├── base.py                 # Abstract channel interface
│       │   │   ├── telegram.py             # Telegram bot
│       │   │   ├── slack.py                # Slack
│       │   │   ├── discord_bot.py          # Discord webhook
│       │   │   ├── whatsapp.py             # WhatsApp
│       │   │   ├── formatting.py           # Cross-platform message formatting
│       │   │   └── registry.py             # Channel provider registry
│       │   ├── mcp/                        # Model Context Protocol
│       │   │   ├── client.py               # MCP client for server communication
│       │   │   ├── bridge.py               # Bridge MCP tools into agent tool registry
│       │   │   └── manager.py              # MCP server lifecycle management
│       │   └── ...
│       ├── seeds/            # Database seed data
│       │   ├── skills.py     # Marketplace skills (15+ skills)
│       │   └── marketplace_agents.py # Official + community agents
│       ├── worker.py         # ARQ worker for agent tasks
│       ├── auth_external.py  # API key authentication
│       └── agent/            # AI agent system
│           ├── base.py       # Abstract agent interface
│           ├── stream_agent.py # Streaming agent implementation
│           ├── factory.py    # Agent instantiation
│           └── tools/        # Agent tools
│               ├── web_ops/          # Web operations
│               │   ├── search.py     # Multi-provider web search (Tavily/Brave/DuckDuckGo)
│               │   ├── fetch.py      # HTTP requests for web content
│               │   ├── send_message.py # Send messages via channels (Discord, etc.)
│               │   └── providers.py  # Search provider implementations
│               └── skill_ops/        # Skill operations
│                   └── load_skill.py # Load skill instructions at runtime
│
├── app/                      # React frontend
│   └── src/
│       ├── pages/            # Dashboard, Project, Marketplace, Library, etc.
│       ├── components/
│       │   ├── chat/         # ChatContainer, AgentMessage
│       │   ├── panels/       # Architecture, Git, Assets, Kanban
│       │   ├── billing/      # Subscription UI
│       │   ├── marketplace/  # AgentCard, skill/MCP browsing
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
│   ├── terraform/
│   │   └── shared/           # Shared ECR stack (cross-environment)
│   ├── scripts/              # Helper scripts
│   ├── .env.example          # Template for credentials
│   ├── .env.minikube         # Local credentials (gitignored)
│   ├── QUICKSTART.md         # Getting started guide
│   └── ARCHITECTURE.md       # Detailed K8s architecture
│
├── scripts/
│   └── seed/                 # Database seed scripts
│       ├── seed_marketplace_bases.py
│       ├── seed_marketplace_agents.py
│       ├── seed_opensource_agents.py
│       ├── seed_themes.py
│       ├── seed_community_bases.py
│       ├── seed_skills.py          # Skills (open-source + Tesslate)
│       └── seed_mcp_servers.py     # MCP servers (GitHub, Brave, Slack, etc.)
│
└── docker-compose.yml        # Local dev setup (Docker mode)
```

## Key Database Models (models.py)

- **User**: Auth, profile, subscription tier, theme_preset
- **Project**: Name, slug, owner, files, containers
- **ProjectSnapshot**: EBS VolumeSnapshot records for project versioning/timeline
- **Container**: Individual service in a project (frontend, backend, db); includes `startup_command`
- **ContainerConnection**: Dependencies between containers
- **Chat/Message**: Conversation history with AI
- **MarketplaceAgent**: Pre-built AI agents, skills (`item_type='skill'`, `skill_body`), and MCP servers (`item_type='mcp_server'`); includes `git_repo_url`
- **AgentSkillAssignment**: Many-to-many linking skills to agents in a project
- **Deployment**: External deployment records
- **DeploymentCredential**: OAuth tokens for Vercel/Netlify/etc.
- **Theme**: Customizable theme presets with colors, typography, spacing, animations
- **AgentStep**: Append-only agent execution steps (progressive persistence)
- **ExternalAPIKey**: API keys for external agent invocation (SHA-256 hashed)
- **ChannelConfig**: Messaging channel configuration per user (encrypted credentials)
- **ChannelMessage**: Message log for channel interactions
- **UserMcpConfig**: Per-user MCP server installation with encrypted env vars
- **AgentMcpAssignment**: Many-to-many linking MCP servers to agents

## Agent Tools (orchestrator/app/agent/tools/)

| Tool | Purpose |
|------|---------|
| `read_write.py` | Read/write files in project |
| `edit.py` | Edit specific file sections |
| `bash.py` | Execute shell commands |
| `session.py` | Persistent shell sessions |
| `web_ops/fetch.py` | HTTP requests for web content |
| `web_ops/search.py` | Multi-provider web search (Tavily/Brave/DuckDuckGo) |
| `web_ops/send_message.py` | Send messages via channels (Discord webhook, etc.) |
| `skill_ops/load_skill.py` | Load skill instructions at runtime from marketplace |
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
| Database seeding | `docker-dev` skill |
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
| Skills system | `docs/orchestrator/agent/CLAUDE.md` |
| Messaging channels | `docs/orchestrator/routers/CLAUDE.md` → channels.py |
| MCP server integration | `docs/orchestrator/routers/CLAUDE.md` → mcp.py, mcp_server.py |
| Web search tool | `docs/orchestrator/agent/tools/CLAUDE.md` |
| Universal project setup | `docs/orchestrator/routers/CLAUDE.md` → projects.py setup-config |

## Deployment Modes

### Docker (Local Dev)
- `DEPLOYMENT_MODE=docker` in config
- Traefik routes `*.localhost` to containers
- Project files on local filesystem

**For complete Docker setup from scratch, see: [docs/guides/docker-setup.md](docs/guides/docker-setup.md)**

For Docker quick start, clean slate reset, and database seeding scripts, use the **`docker-dev`** skill.

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

# Web Search
web_search_provider: str           # tavily, brave, or duckduckgo (default: tavily)
tavily_api_key: str                # Tavily API key
brave_search_api_key: str          # Brave Search API key

# Messaging Channels
agent_discord_webhook_url: str     # Discord webhook URL for agent send_message tool
channel_encryption_key: str        # Fernet key for channel credential encryption

# MCP (Model Context Protocol)
mcp_tool_cache_ttl: int            # MCP tool schema cache TTL in seconds (300)
mcp_tool_timeout: int              # MCP tool call timeout in seconds (30)
mcp_max_servers_per_user: int      # Max installed MCP servers per user (20)
```

#### Minikube vs Production Config
| Setting | Minikube | Production (AWS EKS) |
|---------|----------|----------------------|
| `K8S_DEVSERVER_IMAGE` | `tesslate-devserver:latest` | `<ECR_REGISTRY>/tesslate-devserver:latest` |
| `K8S_IMAGE_PULL_SECRET` | `` (empty) | `ecr-credentials` |
| `K8S_WILDCARD_TLS_SECRET` | `` (empty, use HTTP) | `tesslate-wildcard-tls` (use HTTPS) |
| `K8S_SNAPSHOT_CLASS` | N/A (not supported) | `tesslate-ebs-snapshots` |

#### Minikube Limitations
- **No VolumeSnapshots**: Minikube doesn't support EBS snapshots, so Timeline/hibernation features won't work
- **HTTP only**: No TLS certificates, all URLs use `http://`
- **Data persistence**: PVCs persist across restarts, but data is lost if cluster is deleted

**For complete minikube setup instructions, see: [docs/guides/minikube-setup.md](docs/guides/minikube-setup.md)**

## Minikube Local Development

For build workflows, image management, quick reference commands, and troubleshooting, use the **`minikube-dev`** skill.

## AWS EKS Production Deployment

For infrastructure details, Terraform deployment, ECR image builds, debugging commands, and troubleshooting, use the **`aws-deploy`** skill.

### AWS Overlay: envFrom Auto-Sync Architecture

The AWS backend overlay (`k8s/overlays/aws-base/backend-patch.yaml`) uses a two-part strategy:

1. **`envFrom`** — auto-mounts ALL keys from 3 terraform-managed secrets (`tesslate-app-secrets`, `postgres-secret`, `s3-credentials`). Adding a new key in terraform's `kubernetes.tf` automatically makes it available in the pod — **no manual kustomize sync needed**.

2. **`env` with `$patch: replace`** — replaces the base manifest's env array with ONLY static values (not in any secret) and 1 alias mapping (`K8S_INGRESS_DOMAIN` → `APP_DOMAIN`). The `$patch: replace` prevents stale base entries from merging in.

**When adding new config:**
- **Secret-based values** (domain, API keys, OAuth, etc.): Add to terraform `kubernetes.tf` secrets → automatically picked up via `envFrom`
- **Static values** (feature flags, class names, etc.): Add to `backend-patch.yaml` env array

### Frontend Config: API_URL Must NOT Include `/api`

The frontend `api-url` in the `frontend-config` ConfigMap (managed by terraform `kubernetes.tf`) must be the **base domain only** (e.g., `https://your-domain.com`), NOT `https://your-domain.com/api`. All API calls in `app/src/lib/api.ts` already include the `/api` prefix in their paths, so including `/api` in the base URL causes double `/api/api/` paths.
