# Docker Infrastructure

Docker Compose configuration for local development.

**File**: `docker compose.yml` (project root)

> **First-time setup?** See [Docker Setup from Scratch](../../guides/docker-setup.md) for the complete walkthrough.

## Overview

Docker Compose provides a simple way to run Tesslate Studio locally for development. It includes:
- Traefik reverse proxy (routing *.localhost)
- PostgreSQL database
- Backend orchestrator (FastAPI)
- Frontend React app (Vite dev server)

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Host Machine (Docker Desktop)                           │
│                                                         │
│  ┌──────────────┐                                      │
│  │   Traefik     │ :80, :443, :8080                    │
│  │   (Routing)   │                                     │
│  └──────┬───────┘                                      │
│         │                                               │
│    ┌────┴──────┬──────────────┐                        │
│    │           │              │                         │
│    ↓           ↓              ↓                         │
│  ┌──────┐  ┌────────────┐  ┌──────────────┐           │
│  │ App  │  │Orchestrator│  │User Projects │           │
│  │:5173 │  │   :8000    │  │(Dynamic)     │           │
│  └──────┘  └─────┬──────┘  └──────────────┘           │
│                   │                                     │
│                   ↓                                     │
│            ┌──────────┐                                │
│            │PostgreSQL│                                │
│            │  :5432   │                                │
│            └──────────┘                                │
└─────────────────────────────────────────────────────────┘
```

## Services

### traefik

**Image**: `traefik:v3.1`
**Ports**: 80 (HTTP), 443 (HTTPS), 8080 (Dashboard)
**Purpose**: Reverse proxy and load balancer

**Routes**:
```
localhost/                → app:5173 (frontend)
localhost/api/*           → orchestrator:8000 (backend)
localhost/ws/*            → orchestrator:8000 (WebSocket)
localhost/traefik         → traefik:8080 (dashboard)
*.localhost               → project containers (via labels)
```

**Configuration**:
- Docker provider (auto-discover containers)
- Constraint: `com.tesslate.routable=true` (route project containers)
- Network: `tesslate-network` (connects to project networks on-demand)

### postgres

**Image**: `postgres:15-alpine`
**Port**: 5432 (exposed for debugging)
**Purpose**: Platform database

**Credentials** (from `.env`):
```
POSTGRES_DB=tesslate_dev
POSTGRES_USER=tesslate_user
POSTGRES_PASSWORD=dev_password_change_me
```

**Volume**: `postgres-dev-data` (persisted between restarts)

**Health Check**: `pg_isready` command

### orchestrator

**Build**: `./orchestrator/Dockerfile`
**Port**: 8000 (exposed for debugging)
**Purpose**: FastAPI backend

**Volumes** (hot reload):
- `./orchestrator/app` → `/app/app`
- `./orchestrator/users` → `/app/users` (project files)
- `/var/run/docker.sock` → container (Docker CLI access)
- `projects-data` → `/projects` (shared with user containers)

**Environment** (key vars):
```yaml
DEPLOYMENT_MODE: docker
DATABASE_URL: postgresql+asyncpg://tesslate_user:...@postgres:5432/tesslate_dev
SECRET_KEY: change-this-in-production
LITELLM_API_BASE: https://your-litellm.com
LITELLM_MASTER_KEY: xxx
APP_PROTOCOL: http
APP_DOMAIN: localhost
```

**Hot Reload**: Uvicorn watches `app/` directory

### app

**Build**: `./app/Dockerfile`
**Port**: 5173 (Vite dev server)
**Purpose**: React frontend with HMR

**Volumes** (hot reload):
- `./app/src` → `/app/src`
- `./app/public` → `/app/public`
- `./app/index.html` → `/app/index.html`
- Config files (vite.config.ts, tsconfig.json, etc.)

**Environment**:
```yaml
VITE_API_URL: (empty, uses relative /api)
APP_DOMAIN: localhost
DEPLOYMENT_MODE: docker
CHOKIDAR_USEPOLLING: true  # For file watcher
```

**Hot Module Replacement**: Vite dev server provides HMR

## Networks

**tesslate-network**:
- Type: Bridge
- Connected services: traefik, postgres, orchestrator, app
- Internal DNS: Service name resolves to container IP

**Project Networks** (created on-demand):
- Type: Bridge
- Named: `tesslate-{project-slug}`
- Traefik connects when project starts

## Volumes

**postgres-dev-data**:
- PostgreSQL data directory
- Persisted between container restarts
- Location: Docker managed volume

**base-cache**:
- Pre-installed marketplace bases
- Shared between backend and user containers
- Speeds up project creation

**projects-data**:
- All user project source code
- Shared between orchestrator and user containers
- Backend has direct read/write access
- Location: Docker managed volume

## Usage

### From-Scratch Setup

```bash
# 1. Copy environment file and configure required values
cp .env.example .env
# Edit .env: set SECRET_KEY, LITELLM_API_BASE, LITELLM_MASTER_KEY

# 2. Build images and start all services
docker compose up --build -d

# 3. Verify everything is running
docker compose ps
```

See [Docker Setup from Scratch](../../guides/docker-setup.md) for the full walkthrough.

### Start Services

```bash
# Start all services in background
docker compose up -d

# Start with rebuild (after dependency changes)
docker compose up -d --build

# View logs
docker compose logs -f

# View specific service logs
docker compose logs -f orchestrator
```

### Access Services

- **Frontend**: http://localhost (via Traefik) or http://localhost:5173 (direct)
- **Backend API**: http://localhost/api (via Traefik) or http://localhost:8000 (direct)
- **API Docs**: http://localhost:8000/docs (Swagger UI)
- **Traefik Dashboard**: http://localhost:8080
- **PostgreSQL**: localhost:5432 (for pgAdmin, DBeaver)

### User Projects

User projects run in separate containers on `tesslate-network`:

**URL pattern**: `http://{container}.localhost`

Example:
```
http://frontend.my-app-k3x8n2.localhost
http://backend.my-app-k3x8n2.localhost
```

Traefik auto-discovers containers with label `com.tesslate.project=true`

### Stop Services

```bash
# Stop containers, keep volumes
docker compose down

# Stop containers, remove volumes
docker compose down -v
```

### Rebuild After Code Changes

```bash
# Rebuild specific service
docker compose up -d --build orchestrator

# Rebuild all
docker compose up -d --build
```

### Reset Database

```bash
# Stop services
docker compose down

# Remove database volume
docker volume rm tesslate-postgres-dev-data

# Restart
docker compose up -d
```

## Development Workflow

### Backend Changes

1. Edit code in `orchestrator/app/`
2. Uvicorn auto-reloads (watch for "Reloading..." in logs)
3. If dependencies changed:
```bash
docker compose exec orchestrator pip install -e .
# OR rebuild:
docker compose up -d --build orchestrator
```

### Frontend Changes

1. Edit code in `app/src/`
2. Vite HMR updates browser automatically
3. If dependencies changed:
```bash
docker compose exec app npm install
# OR rebuild:
docker compose up -d --build app
```

### Database Migrations

```bash
# Generate migration
docker compose exec orchestrator alembic revision --autogenerate -m "description"

# Apply migrations
docker compose exec orchestrator alembic upgrade head

# Rollback
docker compose exec orchestrator alembic downgrade -1
```

### Debugging

**Backend**:
```bash
# Attach to logs
docker compose logs -f orchestrator

# Enter container shell
docker compose exec orchestrator bash

# Run Python REPL
docker compose exec orchestrator python
```

**Frontend**:
```bash
# Attach to logs
docker compose logs -f app

# Enter container
docker compose exec app sh

# Run npm commands
docker compose exec app npm run build
```

**Database**:
```bash
# Enter psql shell
docker compose exec postgres psql -U tesslate_user -d tesslate_dev

# Run SQL file
docker compose exec -T postgres psql -U tesslate_user -d tesslate_dev < script.sql
```

## Traefik Configuration

### Labels

Services use Traefik labels for routing:

```yaml
labels:
  - "com.tesslate.traefik=main"  # Include in routing
  - "traefik.enable=true"
  - "traefik.http.routers.{name}.rule=Host(`localhost`) && PathPrefix(`/api`)"
  - "traefik.http.routers.{name}.entrypoints=web"
  - "traefik.http.services.{name}.loadbalancer.server.port=8000"
```

### Dashboard

Access Traefik dashboard at http://localhost/traefik

**Features**:
- View all routes
- See active services
- Monitor HTTP traffic
- Debug routing issues

**Authentication**: Basic auth (configured in docker compose.yml)

## Environment Variables

Create `.env` file in project root:

```bash
# Core
SECRET_KEY=your-secret-key
DEPLOYMENT_MODE=docker

# Database
POSTGRES_DB=tesslate_dev
POSTGRES_USER=tesslate_user
POSTGRES_PASSWORD=dev_password_change_me

# LiteLLM
LITELLM_API_BASE=https://your-litellm.com
LITELLM_MASTER_KEY=xxx
LITELLM_DEFAULT_MODELS=claude-sonnet-4.6,claude-opus-4.6

# Domain
APP_PROTOCOL=http
APP_DOMAIN=localhost
CORS_ORIGINS=http://localhost
ALLOWED_HOSTS=localhost

# Ports (optional, defaults shown)
APP_PORT=80
APP_SECURE_PORT=443
TRAEFIK_DASHBOARD_PORT=8080
BACKEND_PORT=8000
FRONTEND_PORT=5173
POSTGRES_PORT=5432

# OAuth (optional)
GOOGLE_CLIENT_ID=xxx
GOOGLE_CLIENT_SECRET=xxx
GITHUB_CLIENT_ID=xxx
GITHUB_CLIENT_SECRET=xxx
```

## Troubleshooting

### Port Already in Use

**Symptom**: `bind: address already in use`

**Fix**: Stop conflicting service or change port in `.env`
```bash
APP_PORT=8080  # Use port 8080 instead of 80
```

### Container Fails to Start

**Check logs**:
```bash
docker compose logs orchestrator
```

**Common issues**:
- Database not ready (wait for postgres health check)
- Missing environment variables
- Port conflict

### Hot Reload Not Working

**Backend**:
- Check uvicorn logs for "Reloading..."
- Ensure `./orchestrator/app` is mounted
- Try `WATCHFILES_FORCE_POLLING=true` in env

**Frontend**:
- Check Vite logs for HMR connection
- Ensure `./app/src` is mounted
- Try `CHOKIDAR_USEPOLLING=true` in env

### Database Connection Failed

**Check postgres**:
```bash
docker compose ps postgres
docker compose logs postgres
```

**Verify connection**:
```bash
docker compose exec postgres pg_isready -U tesslate_user
```

### User Project Container Not Accessible

**Check Traefik routes**:
- Dashboard: http://localhost:8080 → Routers
- Look for `{container}.localhost` route

**Verify labels**:
```bash
docker inspect {container_name} | grep -A 10 Labels
```

## Best Practices

1. **Use .env file**: Never commit secrets to git
2. **Hot reload only**: Don't rebuild unless dependencies changed
3. **Clean up orphaned containers**: `docker system prune` regularly
4. **Use Docker Desktop**: Easier on Windows/Mac than Docker Engine
5. **Monitor resources**: Docker Desktop → Settings → Resources

## Comparison with Kubernetes

| Feature | Docker Compose | Kubernetes |
|---------|----------------|------------|
| **Routing** | Traefik (*.localhost) | NGINX Ingress (domain) |
| **Projects** | Direct filesystem | S3 Sandwich pattern |
| **Isolation** | Shared network | Namespace per project |
| **Storage** | Bind mounts / volumes | PVCs |
| **Scaling** | Manual | Automatic |
| **Use Case** | Local development | Production |

## Clean Slate Reset

Remove everything and start from scratch:

```bash
# 1. Stop and remove containers + volumes
docker compose down --volumes --remove-orphans

# 2. Remove all tesslate images
docker images --format "{{.Repository}}:{{.Tag}} {{.ID}}" | grep -i tesslate | awk '{print $2}' | sort -u | xargs docker rmi -f

# 3. Rebuild from scratch
docker compose up --build -d
```

## Related Documentation

- [Docker Setup from Scratch](../../guides/docker-setup.md): Complete first-time setup guide
- [CLAUDE.md](CLAUDE.md): Docker agent context (quick reference)
- [dockerfiles.md](dockerfiles.md): Dockerfile documentation
- [docker-compose.md](docker-compose.md): Compose file details
