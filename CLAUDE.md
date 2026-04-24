Never add claude as a contributor to github.

You are a senior level coding agent. You will apply real world solutions to all the problems, fixing them in such a way where you do not cheat the solution, break existing functionality, and are scoped in. The solutions you write must be scalable and for the future, not fixing or hardcoding.

## CRITICAL RULE: Investigation is READ-ONLY

When the user describes an issue, pastes an error, asks a question, or says "investigate" / "dive deep" / "look into":
- **ONLY** read files, search code, and explain findings in text
- **NEVER** edit, write, or modify any code or infrastructure
- **ALWAYS** ask "Want me to implement this?" before touching anything
- This is NON-NEGOTIABLE. Violating this is a session-ending event.

Always read through the docs/ to find items it is a knowledgegraph

## Research Folder

The `research/` directory is gitignored and contains cloned repos for reference/research:
- `research/hermes-agent/` — [NousResearch/hermes-agent](https://github.com/nousresearch/hermes-agent) — Hermes agent framework

Use subagents generously if you are doing bulk task items that have a small / atomic scope.

don't do conditional logic for k8s and docker implementation differences. try to keep it as similar as possible unless if a platform requires differeces. Prioritize the k8s (keep that logic more intact than docker. )

On windows use MSYS_NO_PATHCONV=1 while running kubectl or docker exec commands.
The ECR IS <AWS_ACCOUNT_ID> not <AWS_ACCOUNT_ID>

**CRITICAL: kubectl Context Safety** — EVERY `kubectl` command MUST include `--context=<name>`. NEVER use `kubectl config use-context`, `./scripts/kctx.sh`, or any context-switching command. Context switching is BANNED because cronjobs and other processes can change it mid-session, causing accidental production mutations. Use: `kubectl --context=tesslate` (minikube), `kubectl --context=tesslate-production-eks` (prod), `kubectl --context=tesslate-beta-eks` (beta). See `docs/infrastructure/kubernetes/CLAUDE.md` for details.

**CRITICAL: AWS/EKS team roles** — Before any `aws` / `kubectl` against beta or production, assume a team role: `arn:aws:iam::<AWS_ACCOUNT_ID>:role/tesslate-{env}-eks-team-{observer|deployer|debugger|admin}` (least-privilege: observer=read+logs, deployer=rollout+ECR push, debugger=exec, admin=secrets/RBAC). Do NOT assume `eks-deployer` — that's a legacy admin-only role (`eks_admin_iam_arns` = `<AWS_IAM_USER>` + `tesslate-bigboss`); regular users (in `tesslate-{env}-{observers,deployers,debuggers,admins}` IAM groups) get `AccessDenied`. `./scripts/aws-deploy.sh` defaults to `team-deployer`; override with `AWS_EKS_ROLE_ARN=...` for admin-only roles. Full reference: `docs/guides/eks-cluster-access.md`.

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

# OpenSail

When I have an issue, fix it for the next time it happens in a general, scalable way. For example, if a container fails on startup, ensure all future container startups work 100%.

## What is OpenSail?

AI-powered web application builder that lets users create, edit, deploy, and manage full-stack apps using natural language. Users describe what they want, an AI agent writes the code, and the platform handles containerized deployment. Projects can be published as distributable Apps on the Tesslate marketplace.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    OpenSail                                 │
├─────────────────────────────────────────────────────────────┤
│  Desktop (desktop/)        │  Frontend (app/)               │
│  Tauri v2 shell            │  React + Vite + TypeScript     │
│  - PyInstaller sidecar     │  - Monaco Editor               │
│  - System tray             │  - Live Preview / Chat UI      │
│  - Stronghold token store  │  - Architecture Panel          │
├─────────────────────────────────────────────────────────────┤
│  Orchestrator (orchestrator/)                               │
│  FastAPI + Python                                           │
│  - Auth (JWT/OAuth)        - AI Agent System                │
│  - Project Management      - Container Orchestration        │
│  - Tesslate Apps pipeline  - Gateway / Channels             │
├─────────────────────────────────────────────────────────────┤
│  Task Queue / Pub-Sub                                       │
│  Cloud: Redis 7.x + ARQ (ArqTaskQueue + RedisPubSub)        │
│  Desktop: asyncio.Queue + apscheduler (LocalTaskQueue +     │
│           LocalPubSub)                                      │
├─────────────────────────────────────────────────────────────┤
│  PostgreSQL (cloud)  │  SQLite (desktop, aiosqlite)         │
│  User data, projects │  Same models, GUID TypeDecorator     │
├─────────────────────────────────────────────────────────────┤
│  Docker/Kubernetes/Local Container Manager                  │
│  - Per-project isolation    - Per-project runtime column    │
│  - factory.py resolves orchestrator per project.runtime     │
├─────────────────────────────────────────────────────────────┤
│  Volume Hub (services/btrfs-csi)                            │
│  - btrfs CSI driver (per-node subvolume mgmt)               │
│  - Volume Hub (storageless orchestrator, cache placement)   │
│  - S3/CAS sync (content-addressable object persistence)     │
│  - Template builder (instant snapshot-clone for new projects)│
└─────────────────────────────────────────────────────────────┘
```

## Technology Stack

| Layer | Tech |
|-------|------|
| Frontend | React 19, TypeScript, Vite, Tailwind, Monaco Editor |
| Desktop shell | Tauri v2 (Rust), tauri-plugin-stronghold, tray, deep-link, updater |
| Backend | FastAPI, Python 3.11, SQLAlchemy, LiteLLM |
| Agent runner | `packages/tesslate-agent` (Python submodule) |
| Database | PostgreSQL/asyncpg (cloud), SQLite/aiosqlite (desktop) |
| Task Queue | Redis 7.x + ARQ (cloud), asyncio + apscheduler (desktop) |
| Containers | Docker Compose (dev), Kubernetes (prod), Local subprocesses (desktop) |
| Storage | btrfs CSI + Volume Hub (Go), S3/CAS persistence |
| Routing | Traefik (Docker), NGINX Ingress (K8s), direct 127.0.0.1 (desktop) |
| AI | LiteLLM → OpenAI/Anthropic models; cloud proxy via `cloud_client.py` |
| Payments | Stripe |
| Apps SDK | `packages/tesslate-app-sdk` (Python), `packages/tesslate-embed-sdk` (TypeScript) |

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

### 5. Gateway (Communication Protocol v2)
```
POST /api/gateway/status → routers/gateway.py
Gateway runner → services/gateway/runner.py
  ├─ Hot-reload adapters via Redis pub/sub
  ├─ Platform adapters (Telegram, Discord, Slack, WhatsApp, Signal, CLI)
  ├─ Identity pairing (link platform accounts)
  ├─ Cron scheduler (timezone-aware)
  └─ Delivery stream (Redis XREADGROUP for response routing)
```

## Directory Structure (top-level)

```
tesslate-studio/
├── desktop/         # Tauri v2 shell — src-tauri (Rust), sidecar (PyInstaller), scripts
├── packages/        # Submodules: tesslate-agent, tesslate-app-sdk, tesslate-embed-sdk
├── orchestrator/    # FastAPI backend — routers/, services/, agent/, seeds/, worker.py
├── app/             # React frontend — pages/, components/, contexts/, layouts/, lib/
├── k8s/             # Kubernetes (Kustomize) — base/, overlays/, terraform/, scripts/
├── services/        # Standalone services — btrfs-csi/ (Go), tsinit/
├── sdk/             # Top-level @tesslate/sdk TypeScript client
├── seeds/           # Seed Tesslate Apps
├── scripts/         # Deploy, seed, migration scripts
├── docs/            # Knowledge graph (see Subfolder Index below)
└── docker-compose.yml
```

For deep nesting (per-subdir file lists) load the corresponding `CLAUDE.md` from the **Subfolder CLAUDE.md Index** below.

## Key Database Models (models.py)

- **User**: Auth, profile, subscription tier, theme_preset
- **Project**: Name, slug, owner, files, containers, `volume_id`, `cache_node`, `compute_tier` (none/ephemeral/environment), `active_compute_pod`, `last_sync_at`, `template_storage_class`, `team_id`, `visibility` (team/private), `runtime` (local|docker|k8s), `sync_enabled`, `app_role` (none/app_source/app_instance)
- **ProjectSnapshot**: VolumeSnapshot records for project versioning/timeline
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
- **Team**: Name, slug, avatar, is_personal, billing (subscription_tier, credits, stripe), created_by_id
- **TeamMembership**: User ↔ Team with role (admin/editor/viewer), is_active
- **ProjectMembership**: User ↔ Project role override (editor/viewer), granted_by_id
- **TeamInvitation**: Email + link invites, token, expiry, max_uses, use_count
- **AuditLog**: Team + project scoped event trail, action, resource_type, details JSON
- **PlatformIdentity**: Platform account linking for gateway (user_id nullable for unlinked)
- **AgentSchedule**: Cron schedules with timezone, repeat count, delivery target
- **Directory**: Connected local/docker/k8s directories for desktop unified workspace (path, runtime, project_id, git_root)

### Tesslate Apps Models

- **MarketplaceApp**: App identity anchor (slug, handle, category, state, creator_id, forkable, reputation)
- **AppVersion**: Immutable published version (manifest JSON, CAS bundle address, approval_state, semver)
- **AppInstance**: Per-user app install (installer_user_id, project_id, wallet_mix, update_policy: auto/manual/pinned)
- **AppInstallAttempt**: Saga ledger for idempotent install; records volume_id for reaper cleanup on crash
- **AppSubmission**: Staged approval pipeline row (stage0→stage1→stage2→stage3→approved|rejected)
- **SubmissionCheck**: Individual per-stage check result (passed/failed/warning/errored)
- **YankRequest**: Unpublish request with severity (low/medium/critical); critical requires 2-admin approval
- **YankAppeal**: Creator appeal against a yank decision
- **AppBundle**: Curated collection of AppVersions (e.g., "Tesslate Starter Pack")
- **AppBundleItem**: Ordered membership of AppVersion in a bundle

Full model reference → `docs/orchestrator/models/CLAUDE.md`. Apps feature detail → `docs/apps/CLAUDE.md`.

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
| `project_control.py` | Container lifecycle control (status, restart, logs, health) |
| `kanban.py` | Kanban board management (create/move/update tasks by TSK-NNNN ref, columns, comments) |
| `schedule_ops/manage_schedule.py` | Manage cron schedules (create/update/delete/pause/resume) |

Tool registry internals, scope enforcement, edit-mode gating, secret scrubbing → `docs/orchestrator/agent/CLAUDE.md`.

## Subfolder CLAUDE.md Index

Load the most specific CLAUDE.md first, then follow its "Related Contexts" links outward. **Primary doc entry point: [docs/CLAUDE.md](docs/CLAUDE.md)** — full navigation guide, "I need to…" table, env var reference.

### Code directories (in-tree CLAUDE.md)

| Path | What it covers |
|------|----------------|
| [desktop/CLAUDE.md](desktop/CLAUDE.md) | Tauri v2 shell root |
| [desktop/src-tauri/CLAUDE.md](desktop/src-tauri/CLAUDE.md) | Rust: sidecar supervisor, tray, Stronghold tokens, deep-link, updater |
| [desktop/sidecar/CLAUDE.md](desktop/sidecar/CLAUDE.md) | PyInstaller build for the FastAPI sidecar |
| [desktop/scripts/CLAUDE.md](desktop/scripts/CLAUDE.md) | build-all.sh, dev.sh |
| [orchestrator/app/routers/CLAUDE.md](orchestrator/app/routers/CLAUDE.md) | Router code-site conventions (complements docs) |
| [orchestrator/tests/routers/CLAUDE.md](orchestrator/tests/routers/CLAUDE.md) | Router test conventions |
| [orchestrator/tests/orchestration/CLAUDE.md](orchestrator/tests/orchestration/CLAUDE.md) | Docker/K8s orchestrator test conventions |
| [orchestrator/tests/agent_bridge/CLAUDE.md](orchestrator/tests/agent_bridge/CLAUDE.md) | Agent bridge test conventions |

### Documentation knowledge graph (`docs/`)

**Architecture & backend**

| Path | What it covers |
|------|----------------|
| [docs/architecture/CLAUDE.md](docs/architecture/CLAUDE.md) | System architecture, data-flow patterns, deployment-mode internals, principles (non-blocking, scalable, isolation) |
| [docs/orchestrator/CLAUDE.md](docs/orchestrator/CLAUDE.md) | FastAPI backend overview, middleware, env vars, K8s-name derivation rule |
| [docs/orchestrator/routers/CLAUDE.md](docs/orchestrator/routers/CLAUDE.md) | Every router, auth matrix, common patterns |
| [docs/orchestrator/services/CLAUDE.md](docs/orchestrator/services/CLAUDE.md) | Business logic (orchestration, pubsub, channels, MCP, apps) |
| [docs/orchestrator/agent/CLAUDE.md](docs/orchestrator/agent/CLAUDE.md) | Agent tool registry, scope/edit-mode gating, approval, secret scrubbing |
| [docs/orchestrator/models/CLAUDE.md](docs/orchestrator/models/CLAUDE.md) | All SQLAlchemy models (60+), query patterns, field reference |
| [docs/orchestrator/orchestration/CLAUDE.md](docs/orchestrator/orchestration/CLAUDE.md) | Container lifecycle (Docker/K8s/local) |

**Frontend**

| Path | What it covers |
|------|----------------|
| [docs/app/CLAUDE.md](docs/app/CLAUDE.md) | React frontend overview |
| [docs/app/pages/CLAUDE.md](docs/app/pages/CLAUDE.md) | Route components (Dashboard, Project, Marketplace, Settings, etc.) |
| [docs/app/components/CLAUDE.md](docs/app/components/CLAUDE.md) | Chat, panels, billing, marketplace, modals |
| [docs/app/api/CLAUDE.md](docs/app/api/CLAUDE.md) | API client (`lib/api.ts`) |
| [docs/app/state/CLAUDE.md](docs/app/state/CLAUDE.md) | State management |
| [docs/app/contexts/CLAUDE.md](docs/app/contexts/CLAUDE.md) | Auth, Command, Marketplace, Team contexts |
| [docs/app/hooks/CLAUDE.md](docs/app/hooks/CLAUDE.md) | useCancellable, useAuth, useTask |
| [docs/app/keyboard-shortcuts/CLAUDE.md](docs/app/keyboard-shortcuts/CLAUDE.md) | Command palette & shortcut system |
| [docs/app/layouts/CLAUDE.md](docs/app/layouts/CLAUDE.md) | Settings, Marketplace page layouts |
| [docs/app/utils/CLAUDE.md](docs/app/utils/CLAUDE.md), [seo/](docs/app/seo/CLAUDE.md), [types/](docs/app/types/CLAUDE.md) | Utility, SEO, shared TS types |

**Infrastructure**

| Path | What it covers |
|------|----------------|
| [docs/infrastructure/CLAUDE.md](docs/infrastructure/CLAUDE.md) | DevOps overview, deployment modes, S3 Sandwich pattern, network policies, RBAC |
| [docs/infrastructure/kubernetes/CLAUDE.md](docs/infrastructure/kubernetes/CLAUDE.md) | K8s manifests, Volume Hub + btrfs CSI, **orchestrator config settings**, **minikube↔prod mapping**, **AWS overlay conventions**, security layers |
| [docs/infrastructure/docker/CLAUDE.md](docs/infrastructure/docker/CLAUDE.md) | Docker image / dependency management |
| [docs/infrastructure/docker-compose/CLAUDE.md](docs/infrastructure/docker-compose/CLAUDE.md) | Root `docker-compose*.yml` files |
| [docs/infrastructure/terraform/CLAUDE.md](docs/infrastructure/terraform/CLAUDE.md) | AWS + shared Terraform stacks (EKS, ECR, S3, IAM, DNS) |
| [docs/infrastructure/traefik/CLAUDE.md](docs/infrastructure/traefik/CLAUDE.md) | Traefik routing (Docker mode only) |

**Features & platform**

| Path | What it covers |
|------|----------------|
| [docs/desktop/CLAUDE.md](docs/desktop/CLAUDE.md) | Desktop runtimes (local/docker/k8s), sync, permissions, notifications, TUI |
| [docs/apps/CLAUDE.md](docs/apps/CLAUDE.md) | Tesslate Apps: publish, install, approval pipeline, billing, yank, fork, bundles |
| [docs/packages/CLAUDE.md](docs/packages/CLAUDE.md) | `tesslate-agent`, `tesslate-app-sdk`, `tesslate-embed-sdk` submodules |
| [docs/sdk/CLAUDE.md](docs/sdk/CLAUDE.md) | Top-level `@tesslate/sdk` TypeScript client |
| [docs/services/btrfs-csi/CLAUDE.md](docs/services/btrfs-csi/CLAUDE.md) | btrfs CSI driver + Volume Hub (Go) |
| [docs/services/tsinit/CLAUDE.md](docs/services/tsinit/CLAUDE.md) | In-container supervisor |

**Ops & meta**

| Path | What it covers |
|------|----------------|
| [docs/scripts/CLAUDE.md](docs/scripts/CLAUDE.md) | Deploy, seed, litellm, migration scripts |
| [docs/seeds/CLAUDE.md](docs/seeds/CLAUDE.md) | Seed Tesslate Apps |
| [docs/ci-cd/CLAUDE.md](docs/ci-cd/CLAUDE.md) | CI/CD workflows |
| [docs/testing/CLAUDE.md](docs/testing/CLAUDE.md) | Test conventions across the repo |
| [docs/linear/CLAUDE.md](docs/linear/CLAUDE.md) | Linear integration docs |

## Deployment Modes

| Mode | Config | Use case |
|------|--------|----------|
| Desktop | `DEPLOYMENT_MODE=desktop` | Tauri app — SQLite + local queue, per-project `runtime` column (local/docker/k8s-remote) |
| Docker | `DEPLOYMENT_MODE=docker` | Local dev — Traefik routes `*.localhost` |
| Kubernetes | `DEPLOYMENT_MODE=kubernetes` | Minikube / EKS — per-project namespaces, btrfs CSI + Volume Hub, NGINX Ingress |

Detailed mode architecture → [docs/architecture/CLAUDE.md](docs/architecture/CLAUDE.md). K8s config settings, minikube↔prod mapping, Volume Hub + btrfs CSI, and AWS overlay conventions → [docs/infrastructure/kubernetes/CLAUDE.md](docs/infrastructure/kubernetes/CLAUDE.md).

### Minikube limitations
- HTTP only (no TLS certs), all URLs use `http://`
- PVCs persist across restarts but data is lost if the cluster is deleted

For build workflows, image management, and troubleshooting, use the **`minikube-dev`** skill (local) or **`aws`** skill (production / beta — covers logs, exec, debug, deploy).
