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

**Docker Mode** (default - local development & production):
- Uses Docker containers with Traefik hostname-based routing
- Local file storage in `users/{user_id}/{project_id}/`
- Container naming: `builder-dev-user{id}-project{id}`
- **Local dev routing**: `http://user{id}-project{id}.localhost`
- **Production routing**: `https://user{id}-project{id}.yourdomain.com` (with wildcard DNS)

**Kubernetes Mode** (production):
- Uses K8s Deployments, Services, and Ingresses
- Shared PVC storage with subPath isolation
- Pod naming: `dev-user{id}-project{id}`
- HTTPS routing: `https://user{id}-project{id}.studio-test.tesslate.com`

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
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Required environment variables:**
   - `SECRET_KEY`: JWT secret key for authentication
   - `DATABASE_URL`: Database connection (SQLite or PostgreSQL)
   - `DEPLOYMENT_MODE`: `docker` or `kubernetes`
   - `OPENAI_API_KEY`: Your OpenAI API key
   - `OPENAI_API_BASE`: API base URL (default: https://api.openai.com/v1)
   - `OPENAI_MODEL`: Model to use (e.g., gpt-4, gpt-3.5-turbo)

4. **Optional environment variables:**
   - `DEV_SERVER_BASE_URL`: Production domain for wildcard routing (e.g., `https://studio-demo.tesslate.com`)
     - Leave empty for local development (uses `.localhost` domains)
     - Set for production to enable `https://user{id}-project{id}.yourdomain.com` URLs
   - `CORS_ORIGINS`: Comma-separated list of allowed CORS origins
   - `ALLOWED_HOSTS`: Comma-separated list of allowed hostnames

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

- **Development**: SQLite (`sqlite+aiosqlite:///./builder.db`)
- **Production**: PostgreSQL (`postgresql+asyncpg://...`)

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
- Direct Docker API integration via subprocess
- Traefik hostname-based routing (supports wildcard DNS for production)
- Local filesystem storage with volume mounts
- **Local dev**: HTTP on `.localhost` domains
- **Production**: HTTPS on wildcard subdomains (requires Cloudflare or Let's Encrypt)

### Kubernetes Mode
- Managed by `k8s_container_manager.py`
- Official Kubernetes Python client for pod lifecycle
- NGINX Ingress Controller with hostname-based routing
- PersistentVolumeClaim storage with subPath isolation
- Always uses HTTPS with wildcard SSL certificates

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