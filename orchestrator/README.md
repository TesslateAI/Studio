# Tesslate Studio - Orchestrator Service

Backend orchestration service for the Tesslate Studio platform. Handles user authentication, project management, and container lifecycle orchestration with support for both Docker and Kubernetes deployments.

## 🚀 Features

- 🔐 **JWT Authentication** - Secure user authentication with access and refresh tokens
- 👥 **Multi-user Support** - Isolated project environments per user
- 🐳 **Dual Deployment Modes** - Support for both Docker and Kubernetes
- 📁 **Project Management** - CRUD operations for user projects and files
- 🤖 **AI Chat Integration** - WebSocket-based streaming chat with AI assistant
- 🔄 **Real-time Updates** - File streaming and live project updates
- 🛠️ **Agent System** - Tool-calling agents for advanced automation

## 🏗️ Architecture

### Container Management Modes

The orchestrator supports two deployment modes configured via `DEPLOYMENT_MODE`:

**Docker Mode** (default - local development):
- Uses Docker containers with Traefik routing
- Local file storage in `users/{user_id}/projects/{project_id}/`
- Container naming: `user{id}-project{id}`
- Routing: `user{id}-project{id}.localhost`

**Kubernetes Mode** (production):
- Uses K8s Deployments, Services, and Ingresses
- Shared PVC storage with subPath isolation
- Pod naming: `dev-user{id}-project{id}`
- HTTPS routing: `user{id}-project{id}.studio-test.tesslate.com`

### API Endpoints

- **Authentication** (`/api/auth`): Login, signup, token refresh
- **Projects** (`/api/projects`): CRUD operations for projects and files
- **Chat** (`/api/chat`): WebSocket streaming chat with AI
- **Agent** (`/api/agent`): Tool-calling agent execution

## 📦 Setup

1. **Install dependencies:**
   ```bash
   cd orchestrator
   uv sync
   ```

2. **Configure environment:**

   For Docker Compose (recommended):
   ```bash
   # From project root
   cp .env.example .env
   # Edit .env with your configuration
   ```

   For native development:
   ```bash
   # Export environment variables or use a .env loader at project root
   # The orchestrator reads from environment variables
   ```

3. **Required environment variables:**
   - `SECRET_KEY`: JWT secret key for authentication
   - `DATABASE_URL`: Database connection (SQLite or PostgreSQL)
   - `DEPLOYMENT_MODE`: `docker` or `kubernetes`
   - `LITELLM_API_BASE`: LiteLLM proxy URL (e.g., http://localhost:4000/v1)
   - `LITELLM_MASTER_KEY`: LiteLLM master API key for managing user keys
   - `OPENAI_API_BASE`: Points to LiteLLM proxy (same as LITELLM_API_BASE)
   - `OPENAI_MODEL`: Model to use via LiteLLM (e.g., gpt-4, cerebras/llama3.1-8b)

## 🏃 Running the Service

### Standalone Development:
```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### With Docker Compose:
```bash
# From project root
docker compose up orchestrator
```

API will be available at:
- Standalone: http://localhost:8000
- Docker Compose: http://api.localhost

## 🗄️ Database

The orchestrator uses SQLAlchemy with async support:

- **All Environments**: PostgreSQL (`postgresql+asyncpg://...`)

Database tables are automatically created on startup with retry logic for resilience.

## 🔒 Security Features

- JWT-based authentication with refresh tokens
- CORS protection with explicit origin whitelisting
- Security headers (CSP, X-Frame-Options, etc.)
- Request/response logging
- Environment-based configuration

## 🐳 Container Orchestration

### Docker Mode
- Managed by `docker_container_manager.py`
- Direct Docker API integration
- Traefik routing configuration
- Local filesystem storage

### Kubernetes Mode
- Managed by `k8s_container_manager.py`
- K8s client for pod lifecycle
- Ingress-based routing
- PersistentVolumeClaim storage

## 📚 Project Structure

```
orchestrator/
├── app/
│   ├── agent/              # Agent system with tools
│   ├── routers/            # API route handlers
│   ├── services/           # Business logic
│   ├── auth.py             # Authentication utilities
│   ├── config.py           # Configuration management
│   ├── database.py         # Database setup
│   ├── dev_server_manager.py        # Deployment facade
│   ├── docker_container_manager.py  # Docker implementation
│   ├── k8s_container_manager.py     # K8s implementation
│   ├── k8s_client.py       # Kubernetes client
│   ├── main.py             # FastAPI application
│   ├── models.py           # Database models
│   └── schemas.py          # Pydantic schemas
├── backend/                # Legacy backend (deprecated)
├── k8s/                    # Kubernetes configs for this service
├── template/               # Dev server templates
├── Dockerfile              # Production image
├── Dockerfile.devserver    # Dev server image
├── pyproject.toml          # Python dependencies
└── README.md               # This file
```

## 🔗 Integration

This service integrates with:
- **app/** - Frontend React application
- **traefik/** - Reverse proxy and routing (Docker mode)
- **k8s/** - Kubernetes deployment manifests

The orchestrator includes built-in AI integration with OpenAI, Anthropic, and Cerebras models.

See the [main README](../README.md) for full architecture documentation.