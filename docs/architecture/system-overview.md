# System Overview

This document provides a comprehensive overview of Tesslate Studio's architecture, including the complete technology stack, system responsibilities, data flow, external integrations, and security design.

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                      Tesslate Studio                             │
│                  AI-Powered App Builder                          │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────────┐         ┌──────────────────────┐       │
│  │   Frontend (app/)  │ ←────→  │ Orchestrator (API)   │       │
│  │                    │  HTTP   │                      │       │
│  │ React + TypeScript │ WebSkt  │ FastAPI + Python     │       │
│  │ Monaco Editor      │         │ SQLAlchemy + LiteLLM │       │
│  │ Live Preview       │         │ Agent System         │       │
│  └────────────────────┘         └──────────────────────┘       │
│           │                              │                      │
│           │                              ↓                      │
│           │                     ┌──────────────────┐            │
│           │                     │   PostgreSQL     │            │
│           │                     │                  │            │
│           │                     │ User data        │            │
│           │                     │ Projects         │            │
│           │                     │ Chat history     │            │
│           │                     └──────────────────┘            │
│           │                              │                      │
│           ↓                              ↓                      │
│  ┌────────────────────────────────────────────────────┐        │
│  │     Container Orchestration Layer                  │        │
│  │  (Docker Compose OR Kubernetes)                    │        │
│  └────────────────────────────────────────────────────┘        │
│           │                              │                      │
│           ↓                              ↓                      │
│  ┌─────────────────┐           ┌─────────────────┐            │
│  │ User Project 1  │           │ User Project N  │            │
│  │ (Isolated Env)  │    ...    │ (Isolated Env)  │            │
│  │                 │           │                 │            │
│  │ Frontend + API  │           │ Frontend + API  │            │
│  │ + Database      │           │ + Database      │            │
│  └─────────────────┘           └─────────────────┘            │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Visual Reference**: For a detailed architecture diagram, see `diagrams/high-level-architecture.mmd` (when created).

## Complete Technology Stack

### Frontend Layer

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Framework** | React | 19.x | UI component library |
| **Language** | TypeScript | 5.x | Type-safe JavaScript |
| **Build Tool** | Vite | 5.x | Fast dev server & bundler |
| **Styling** | Tailwind CSS | 3.x | Utility-first CSS framework |
| **Code Editor** | Monaco Editor | Latest | VSCode-based code editing |
| **State Management** | React Context | Built-in | Auth, project, agent state |
| **Routing** | React Router | 6.x | Client-side navigation |
| **HTTP Client** | Axios | Latest | API communication |
| **WebSockets** | EventSource | Native | Server-sent events for streaming |

**Key Files**:
- Entry: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/App.tsx`
- API Client: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/lib/api.ts`
- Components: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/components/`
- Pages: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/`

### Backend Layer (Orchestrator)

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Framework** | FastAPI | Latest | Modern async Python web framework |
| **Language** | Python | 3.11 | Backend programming language |
| **ORM** | SQLAlchemy | 2.x | Database ORM with async support |
| **Database Driver** | asyncpg | Latest | Async PostgreSQL driver |
| **Authentication** | fastapi-users | Latest | User auth & OAuth integration |
| **AI Gateway** | LiteLLM | Latest | Multi-model AI proxy (OpenAI, Anthropic) |
| **Container Orchestration** | kubernetes (Python client) | <32.0.0 | K8s API interaction |
| **S3 Client** | boto3 | Latest | Object storage (AWS S3, MinIO, DO Spaces) |
| **Process Management** | asyncio | Built-in | Async task execution |
| **Payments** | Stripe SDK | Latest | Subscription billing |

**Key Files**:
- Entry: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/main.py`
- Config: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/config.py`
- Models: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/models.py`
- Routers: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/`
- Services: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/`

### Database Layer

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Database** | PostgreSQL | 14+ | Primary data store |
| **Connection Pooling** | SQLAlchemy pool | Built-in | Async connection management |
| **Migrations** | Alembic | Latest | Schema version control |

**Schema** (from `models.py`):
- `users` - User accounts, OAuth tokens, subscriptions
- `projects` - Project metadata, owner, slug, settings
- `containers` - Individual services per project (frontend, backend, db)
- `container_connections` - Dependency graph between containers
- `chats` - Chat sessions with AI agents
- `messages` - Individual chat messages
- `marketplace_agents` - Pre-built AI agents for purchase
- `deployments` - External deployment records
- `deployment_credentials` - OAuth tokens for Vercel/Netlify/etc.
- `shell_sessions` - Persistent bash sessions
- `kanban_tasks` - Project task management

### Container Runtime Layer

#### Docker Mode (Local Development)

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Container Runtime** | Docker Desktop | Run containers on local machine |
| **Orchestration** | Docker Compose | Multi-container project management |
| **Routing** | Traefik | Reverse proxy (*.localhost routing) |
| **Storage** | Local filesystem | Direct volume mounts |

**Note**: Docker orchestrator code was removed (legacy). Projects use direct filesystem access in Docker mode.

#### Kubernetes Mode (Production)

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Cluster** | Kubernetes | Container orchestration |
| **Ingress** | NGINX Ingress | HTTP routing & SSL termination |
| **Storage** | S3 + PVC | S3 Sandwich pattern (ephemeral + persistent) |
| **Networking** | NetworkPolicy | Zero cross-project communication |
| **Cert Management** | cert-manager | Automatic SSL certificate provisioning |
| **DNS** | Cloudflare | DNS management for wildcard domains |

**Key Files**:
- Orchestrator: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/kubernetes_orchestrator.py`
- K8s Client: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/kubernetes/client.py`
- Helpers: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/kubernetes/helpers.py`
- S3 Manager: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/s3_manager.py`
- Manifests: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/`

### AI Agent System

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **LLM Gateway** | LiteLLM | Unified interface for AI models |
| **Streaming** | Server-Sent Events | Real-time agent responses |
| **Tool System** | Custom Python | File ops, bash, session, metadata |
| **Agent Framework** | Custom streaming agent | Tool-calling LLM agent |

**Supported Models** (via LiteLLM):
- OpenAI: GPT-4, GPT-3.5
- Anthropic: Claude 3.5 Sonnet, Claude 3 Opus
- Custom: qwen-3-235b-a22b-thinking-2507 (default)

**Agent Tools** (from `orchestrator/app/agent/tools/`):
- `read_write.py` - Read/write files in project
- `edit.py` - Edit specific file sections
- `bash.py` - Execute shell commands
- `session.py` - Persistent shell sessions
- `fetch.py` - HTTP requests for web content
- `todos.py` - Task planning and tracking
- `metadata.py` - Query project information

**Key Files**:
- Stream Agent: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/agent/stream_agent.py`
- Factory: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/agent/factory.py`
- Base: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/agent/base.py`
- Tools: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/agent/tools/`

## System Responsibilities Breakdown

### Frontend (React App)

**Responsibilities**:
1. **User Interface** - Render UI components, handle user interactions
2. **Code Editing** - Monaco editor integration with IntelliSense
3. **Live Preview** - Embedded iframe showing user project output
4. **Chat UI** - Display agent messages, stream responses
5. **File Browser** - Navigate project files, create/delete/rename
6. **Authentication** - OAuth login flow, JWT/Cookie management
7. **State Management** - User auth, current project, agent state
8. **Routing** - Client-side navigation (Dashboard, Project, Marketplace)

**Does NOT**:
- Execute code (handled by containers)
- Store project files (handled by orchestrator)
- Run AI models (handled by orchestrator → LiteLLM)
- Manage containers (handled by orchestrator)

### Orchestrator (FastAPI Backend)

**Responsibilities**:
1. **Authentication & Authorization** - JWT/OAuth, RBAC, session management
2. **Project Management** - CRUD operations, file tree, metadata
3. **Container Orchestration** - Start/stop containers, health checks, logs
4. **AI Agent System** - Agent instantiation, tool execution, streaming
5. **File Operations** - Read/write/edit files in projects
6. **Git Operations** - Clone, commit, push, pull, branch management
7. **Deployment** - Build & deploy to Vercel/Netlify/Cloudflare
8. **Billing** - Stripe subscriptions, usage tracking, invoices
9. **API Gateway** - Expose REST/WebSocket APIs to frontend
10. **Database Access** - All database queries and updates

**Does NOT**:
- Render UI (handled by frontend)
- Run user code directly (handled by containers)
- Host user applications (handled by containers)

### Database (PostgreSQL)

**Responsibilities**:
1. **User Data** - Accounts, profiles, OAuth tokens, subscription tiers
2. **Project Metadata** - Project names, slugs, owners, settings
3. **Container Definitions** - Container specs, dependencies, ports
4. **Chat History** - Conversation logs with AI agents
5. **Marketplace** - Agent definitions, pricing, purchases
6. **Deployments** - Deployment records, credentials, OAuth tokens
7. **Sessions** - Shell sessions, WebSocket connections
8. **Tasks** - Kanban task tracking

**Does NOT**:
- Store project files (filesystem in Docker, S3+PVC in K8s)
- Store container logs (ephemeral, queried from runtime)
- Store build artifacts (handled by deployment providers)

### Container Runtime (Docker/Kubernetes)

**Responsibilities**:
1. **Isolation** - Each project runs in isolated environment
2. **Resource Management** - CPU/memory limits, quotas
3. **Networking** - Ingress routing, service discovery, NetworkPolicy
4. **Storage** - Volume mounts (Docker) or S3+PVC (K8s)
5. **Health Checks** - Liveness/readiness probes
6. **Scaling** - Horizontal pod autoscaling (K8s only)
7. **SSL/TLS** - Certificate provisioning and termination

**Does NOT**:
- Manage project metadata (handled by database)
- Coordinate across projects (handled by orchestrator)
- Store long-term data (S3 for persistence)

## Data Flow Between Systems

### User Request Lifecycle

```
1. User interacts with Frontend UI
   ↓
2. Frontend sends HTTP/WebSocket request to Orchestrator
   ↓
3. Orchestrator validates auth (JWT/Cookie)
   ↓
4. Orchestrator queries/updates Database
   ↓
5. Orchestrator performs operation:
   ├─ File operation → Container filesystem
   ├─ Container operation → Docker/K8s API
   ├─ AI chat → LiteLLM → OpenAI/Anthropic
   └─ Deployment → Vercel/Netlify API
   ↓
6. Orchestrator returns response to Frontend
   ↓
7. Frontend updates UI with response data
```

### Agent Chat Flow

```
1. User types message in chat UI
   ↓
2. Frontend: POST /api/chat/stream (SSE)
   ↓
3. Orchestrator: routers/chat.py receives request
   ↓
4. Orchestrator: agent/factory.py creates agent instance
   ↓
5. Orchestrator: agent/stream_agent.py executes:
   ├─ Call LLM with system prompt + user message
   ├─ LLM returns tool calls (e.g., write_file)
   ├─ Execute tools in project container
   ├─ Stream tool execution events to frontend
   ├─ Call LLM with tool results
   └─ Stream final response to frontend
   ↓
6. Frontend: Display streaming events in chat UI
```

### Container Start Flow

```
1. User clicks "Start" in project UI
   ↓
2. Frontend: POST /api/projects/{id}/start
   ↓
3. Orchestrator: routers/projects.py receives request
   ↓
4. Orchestrator: Check deployment mode (config.py)
   ↓
5. Kubernetes mode:
   ├─ kubernetes_orchestrator.py.start_project()
   ├─ Create namespace (proj-{uuid})
   ├─ Create PVC (5Gi block storage)
   ├─ Hydrate from S3 (if project exists)
   ├─ Create file-manager pod (always running)
   ├─ Create dev container Deployment + Service
   ├─ Create Ingress rules (NGINX)
   └─ Return container URLs
   ↓
6. Frontend: Poll GET /api/projects/{id}/status
   ↓
7. Status changes: starting → running
   ↓
8. User accesses project at subdomain URL
```

## External Service Integrations

### Authentication Providers

| Provider | Purpose | OAuth Flow |
|----------|---------|-----------|
| **GitHub** | User login | Authorization Code Grant |
| **Google** | User login | Authorization Code Grant |
| **GitLab** | Repository import | Authorization Code Grant |
| **Bitbucket** | Repository import | Authorization Code Grant |

**Implementation**: `orchestrator/app/oauth.py`, `orchestrator/app/main.py`

### AI Model Providers

| Provider | Models | Purpose |
|----------|--------|---------|
| **OpenAI** | GPT-4, GPT-3.5 | Code generation, chat |
| **Anthropic** | Claude 3.5 Sonnet, Claude 3 Opus | Code generation, chat |
| **Custom** | Qwen, DeepSeek | Alternative models |

**Gateway**: LiteLLM (unified interface, rate limiting, usage tracking)

**Implementation**: `orchestrator/app/services/litellm_service.py`

### Deployment Providers

| Provider | Purpose | Integration |
|----------|---------|-------------|
| **Vercel** | Frontend hosting | OAuth + API (git push → auto-deploy) |
| **Netlify** | Frontend hosting | OAuth + API (git push → auto-deploy) |
| **Cloudflare Pages** | Frontend hosting | API (direct upload) |
| **Cloudflare Workers** | Serverless backend | API (wrangler CLI) |

**Implementation**: `orchestrator/app/routers/deployments.py`, `orchestrator/app/routers/deployment_oauth.py`

### Payment Provider

| Provider | Purpose | Integration |
|----------|---------|-------------|
| **Stripe** | Subscriptions, credits, payouts | Stripe SDK + Webhooks |

**Features**:
- Recurring subscriptions (Premium tier)
- One-time credit purchases
- Creator payouts (Stripe Connect)
- Usage-based billing

**Implementation**: `orchestrator/app/routers/billing.py`, `orchestrator/app/routers/webhooks.py`

### Storage Providers

| Provider | Purpose | Protocol |
|----------|---------|----------|
| **AWS S3** | Project storage (production) | S3 API (boto3) |
| **DigitalOcean Spaces** | Project storage (production) | S3 API (boto3) |
| **MinIO** | Project storage (local/dev) | S3 API (boto3) |

**S3 Sandwich Pattern** (Kubernetes only):
1. **Hydration**: Init container downloads project from S3 → PVC
2. **Runtime**: Fast local I/O on PVC for file edits
3. **Dehydration**: PreStop hook uploads project to S3 before pod termination

**Implementation**: `orchestrator/app/services/s3_manager.py`

### DNS Provider

| Provider | Purpose | Integration |
|----------|---------|-------------|
| **Cloudflare** | DNS management, SSL certs | cert-manager (K8s) |

**Features**:
- Wildcard DNS (*.your-domain.com)
- Automatic SSL certificate provisioning (Let's Encrypt)
- DNS-01 challenge for wildcard certs

**Implementation**: `k8s/base/ingress/certificate.yaml`

## Security Architecture

### Authentication & Authorization

**Mechanisms**:
1. **JWT Tokens** (Bearer authentication)
   - Short-lived access tokens (7 days)
   - Refresh tokens (14 days)
   - Stored in `Authorization: Bearer {token}` header

2. **HTTP-Only Cookies** (Session authentication)
   - Secure, HttpOnly, SameSite=Lax
   - Domain-scoped for subdomain access
   - CSRF protection via separate token

3. **OAuth 2.0** (Third-party login)
   - GitHub, Google providers
   - Authorization Code Grant flow
   - State token validation

**Implementation**: `orchestrator/app/users.py`, `orchestrator/app/oauth.py`

### CORS & CSP

**CORS Policy** (Dynamic middleware):
- Allowed origins: `localhost:*`, `*.localhost`, `APP_DOMAIN`, `*.APP_DOMAIN`
- Credentials: Enabled (cookies, auth headers)
- Methods: GET, POST, PUT, DELETE, PATCH, OPTIONS

**Content Security Policy**:
- `default-src`: Self + allowed hosts
- `script-src`: Self + unsafe-inline + unsafe-eval (for Monaco)
- `connect-src`: Self + allowed hosts (WebSocket)
- `frame-src`: Self + allowed hosts (live preview)

**Implementation**: `orchestrator/app/main.py` (DynamicCORSMiddleware)

### CSRF Protection

**Mechanism**: Double Submit Cookie pattern
- CSRF token in cookie (HttpOnly=False, readable by JS)
- CSRF token in `X-CSRF-Token` header (sent by client)
- Server validates tokens match

**Implementation**: `orchestrator/app/middleware/csrf.py`

### Container Isolation (Kubernetes)

**Namespace Isolation**:
- Each project gets dedicated namespace (`proj-{uuid}`)
- Resource quotas per namespace (CPU, memory, storage)
- RBAC rules prevent cross-namespace access

**NetworkPolicy Isolation**:
- Default deny all ingress/egress
- Allow ingress from NGINX Ingress only
- Allow egress to Internet + cluster DNS
- **Zero cross-project communication**

**Example NetworkPolicy** (from `kubernetes/helpers.py`):
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: project-isolation
spec:
  podSelector: {}  # All pods in namespace
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
      - namespaceSelector:
          matchLabels:
            name: ingress-nginx
  egress:
    - to:
      - namespaceSelector: {}  # Cluster DNS
        podSelector:
          matchLabels:
            k8s-app: kube-dns
    - to:
      - namespaceSelector: {}
      ports:
      - protocol: TCP
        port: 443  # HTTPS
      - protocol: TCP
        port: 80   # HTTP
```

**Pod Affinity** (Multi-container projects):
- All containers in same project scheduled on same node
- Enables sharing of RWO (ReadWriteOnce) block storage
- Improves performance (local communication)

**Implementation**: `orchestrator/app/services/orchestration/kubernetes/helpers.py`

### Secrets Management

**Backend Secrets** (K8s):
- Stored in `tesslate-secrets` Secret
- Mounted as environment variables
- Includes: DATABASE_URL, SECRET_KEY, S3 credentials, API keys

**User Project Secrets** (Coming soon):
- Per-project Secret in namespace
- Environment variables injected into containers
- API keys, database credentials, etc.

**Encryption**:
- GitHub tokens: Fernet encryption (derived from SECRET_KEY)
- Deployment credentials: Fernet encryption (DEPLOYMENT_ENCRYPTION_KEY)
- Passwords: bcrypt hashing (fastapi-users)

**Implementation**: `orchestrator/app/encryption.py`

### SSL/TLS

**Production (Kubernetes)**:
- Wildcard certificate (*.your-domain.com)
- Provisioned via cert-manager + Let's Encrypt
- DNS-01 challenge (Cloudflare API)
- Automatic renewal

**Local Development (Docker)**:
- HTTP only (localhost)
- No SSL required for *.localhost domains

**Implementation**: `k8s/base/ingress/certificate.yaml`

## Performance Considerations

### Non-Blocking Design

**Principle**: User requests never block on long operations.

**Examples**:
- Project creation: Background task for container setup
- Deployments: Async build process, webhook on completion
- Agent chat: Streaming responses (no wait for full completion)
- File operations: Async I/O (asyncio, aiofiles)

### Database Optimization

**Strategies**:
- Connection pooling (SQLAlchemy async pool)
- Indexed foreign keys (project_id, user_id, etc.)
- Async queries (no blocking on DB I/O)
- Minimal joins (load related objects lazily)

### Caching

**Base Cache Manager** (Docker mode only):
- Pre-cache project templates in memory
- Fast project creation (copy from cache vs. disk)
- Async initialization (doesn't block startup)

**Implementation**: `orchestrator/app/services/base_cache_manager.py`

### S3 Sandwich Pattern (K8s)

**Benefits**:
1. **Fast I/O**: PVC provides local disk speed
2. **Durability**: S3 backup prevents data loss
3. **Cost Efficiency**: Ephemeral PVCs deleted when unused
4. **Scalability**: Projects can move across nodes

**Trade-offs**:
- Hydration time on first access (mitigated by compression)
- Dehydration time on shutdown (mitigated by background upload)
- S3 costs (mitigated by lifecycle policies)

**Implementation**: `orchestrator/app/services/s3_manager.py`, `kubernetes/helpers.py`

## Monitoring & Logging

### Application Logging

**Levels**: DEBUG, INFO, WARNING, ERROR, CRITICAL (configurable via LOG_LEVEL)

**Format**: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`

**Key Loggers**:
- `app.main` - Request lifecycle
- `app.services.orchestration.kubernetes_orchestrator` - K8s operations
- `app.agent.stream_agent` - Agent execution
- `app.routers.*` - API endpoint handlers

**Implementation**: `orchestrator/app/main.py` (logging.basicConfig)

### Health Checks

**Endpoints**:
- `GET /health` - Backend health (returns 200 if alive)
- `GET /api/config` - Public config (deployment mode, app domain)

**Kubernetes Probes**:
- Liveness: `GET /health` (restart pod if fails)
- Readiness: `GET /health` (remove from load balancer if fails)

**Implementation**: `orchestrator/app/main.py`, `k8s/base/core/backend-deployment.yaml`

### Metrics (Future)

**Planned**:
- Prometheus metrics export
- Request latency histograms
- Container startup time
- Agent response time
- Database query performance

## Scalability & High Availability

### Horizontal Scaling

**Backend (Orchestrator)**:
- ✅ Stateless design (scales horizontally)
- ✅ Database-based coordination (no in-memory state)
- ✅ Multiple replicas supported (K8s Deployment)

**Frontend**:
- ✅ Static build (CDN distribution)
- ✅ Multiple replicas supported (K8s Deployment)

**Database**:
- ⚠️ Single PostgreSQL instance (planned: replicas)
- ✅ Connection pooling (handles high concurrency)

**Limitations**:
- Background tasks (shell cleanup, stats flush) run in-memory per pod
- Solution: Use distributed task queue (Celery, Redis) for critical tasks

### Load Balancing

**Ingress**:
- NGINX Ingress Controller (K8s)
- Round-robin load balancing
- Session affinity not required (stateless backend)

**Service**:
- ClusterIP service for backend (internal LB)
- NodePort for local testing (Minikube)

### Fault Tolerance

**Database Retries**:
- Exponential backoff on connection failures
- Max 5 retries on startup

**S3 Retries**:
- boto3 automatic retries (default: 3 attempts)
- Exponential backoff with jitter

**Container Restarts**:
- K8s restart policy: Always
- Liveness probes detect crashed containers
- Graceful shutdown (SIGTERM → dehydration → exit)

## Future Architecture Enhancements

### Planned Improvements

1. **Distributed Task Queue**
   - Move background tasks to Celery + Redis
   - Ensures tasks complete even if backend pod dies
   - Better observability (task status, retries)

2. **Metrics & Observability**
   - Prometheus for metrics collection
   - Grafana for dashboards
   - OpenTelemetry for distributed tracing

3. **Database Replication**
   - PostgreSQL read replicas
   - Improved read performance
   - High availability

4. **CDN Integration**
   - CloudFlare CDN for frontend
   - Faster global access
   - DDoS protection

5. **Multi-Region Deployment**
   - K8s clusters in multiple regions
   - Geo-routing via DNS
   - Lower latency for global users

6. **Auto-Scaling**
   - Horizontal Pod Autoscaler (HPA) for backend
   - Cluster Autoscaler for K8s nodes
   - Scale based on CPU/memory usage

## Related Documentation

- **[data-flow.md](./data-flow.md)** - Detailed request/response flows
- **[deployment-modes.md](./deployment-modes.md)** - Docker vs. Kubernetes configuration
- **[CLAUDE.md](./CLAUDE.md)** - AI agent context for architecture
- **[../orchestrator/CLAUDE.md](../orchestrator/CLAUDE.md)** - Backend implementation details
- **[../app/CLAUDE.md](../app/CLAUDE.md)** - Frontend implementation details
- **[../../k8s/ARCHITECTURE.md](../../k8s/ARCHITECTURE.md)** - Kubernetes deep dive
