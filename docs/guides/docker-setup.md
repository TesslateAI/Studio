# Docker Setup from Scratch

Complete guide to setting up Tesslate Studio locally using Docker Compose, from a fresh clone to a running application.

## Prerequisites

| Software | Version | Purpose |
|----------|---------|---------|
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | Latest | Container runtime + Docker Compose |
| Git | Latest | Clone the repository |

### System Requirements

- **RAM**: 8GB minimum (16GB recommended)
- **Disk**: 10GB free (images + volumes)
- **OS**: Windows (WSL 2), macOS, or Linux
- **Docker Desktop**: Running with WSL 2 backend (Windows) or native engine (macOS/Linux)

> **Note**: Node.js and Python are NOT required on your host machine. Everything runs inside Docker containers.

## Step-by-Step Setup

### 1. Clone the Repository

```bash
git clone https://github.com/your-org/tesslate-studio.git
cd tesslate-studio
```

### 2. Create Environment File

Copy the example and configure required values:

```bash
cp .env.example .env
```

Open `.env` and update these **required** values:

```bash
# REQUIRED: Change this to a random string
SECRET_KEY=your-secret-key-here-change-this

# REQUIRED: LiteLLM API configuration (for AI features)
LITELLM_API_BASE=https://your-litellm-url.com/v1
LITELLM_MASTER_KEY=your-litellm-master-key
LITELLM_DEFAULT_MODELS=gpt-4o-mini,claude-3-5-sonnet-20241022
```

Everything else has sensible defaults for local development. See the `.env.example` file for the full list of optional settings (OAuth, Stripe, Deployment providers, etc).

### 3. Build and Start

```bash
docker compose up --build -d
```

This builds two images from source and pulls two from Docker Hub:

| Service | Image | Build Time |
|---------|-------|------------|
| `orchestrator` | Built from `orchestrator/Dockerfile` | ~60s |
| `app` | Built from `app/Dockerfile` | ~30s |
| `postgres` | `postgres:15-alpine` (pulled) | instant |
| `traefik` | `traefik:v3.1` (pulled) | instant |

### 4. Verify Everything is Running

```bash
docker compose ps
```

Expected output:

```
NAME                    IMAGE                          STATUS                  PORTS
tesslate-app            tesslate-studio-app            Up (healthy)            0.0.0.0:5173->5173/tcp
tesslate-orchestrator   tesslate-studio-orchestrator   Up (healthy)            0.0.0.0:8000->8000/tcp
tesslate-postgres-dev   postgres:15-alpine             Up (healthy)            0.0.0.0:5432->5432/tcp
tesslate-traefik        traefik:v3.1                   Up                      0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp, 0.0.0.0:8080->8080/tcp
```

All services should show `Up` (and `healthy` where applicable). The orchestrator may show `health: starting` for the first ~30 seconds while it runs database migrations.

### 5. Access the Application

| Service | URL | Description |
|---------|-----|-------------|
| Frontend | http://localhost | Main application (via Traefik) |
| Frontend (direct) | http://localhost:5173 | Vite dev server (bypasses Traefik) |
| Backend API | http://localhost/api | REST API (via Traefik) |
| Backend (direct) | http://localhost:8000 | FastAPI (bypasses Traefik) |
| API Docs | http://localhost:8000/docs | Swagger UI |
| Traefik Dashboard | http://localhost:8080 | Reverse proxy admin panel |
| PostgreSQL | localhost:5432 | Connect with pgAdmin/DBeaver |

The database is auto-initialized on first startup (tables created via Alembic migrations).

## What Gets Created

### Docker Images

| Image | Source | Size |
|-------|--------|------|
| `tesslate-studio-orchestrator` | `orchestrator/Dockerfile` | ~870MB |
| `tesslate-studio-app` | `app/Dockerfile` | ~760MB |

### Docker Volumes

| Volume | Purpose | Persists Between Restarts |
|--------|---------|--------------------------|
| `tesslate-postgres-dev-data` | PostgreSQL database | Yes |
| `tesslate-base-cache` | Pre-installed marketplace bases | Yes |
| `tesslate-projects-data` | All user project source code | Yes |

### Docker Network

| Network | Purpose |
|---------|---------|
| `tesslate-network` | Bridge network connecting all services |

## Clean Slate Reset

If you need to completely reset everything (database, images, volumes):

```bash
# 1. Stop and remove containers + volumes
docker compose down --volumes --remove-orphans

# 2. Remove all project images
docker images --format "{{.Repository}}:{{.Tag}} {{.ID}}" | grep -i tesslate | awk '{print $2}' | sort -u | xargs docker rmi -f

# 3. Rebuild and start fresh
docker compose up --build -d
```

## Development Workflow

### Hot Reload (No Rebuild Needed)

Both backend and frontend support hot reload via volume mounts:

- **Backend**: Edit files in `orchestrator/app/` → Uvicorn auto-reloads
- **Frontend**: Edit files in `app/src/` → Vite HMR updates the browser instantly

### When to Rebuild

Rebuild only when dependencies change:

```bash
# Rebuild a specific service
docker compose up -d --build orchestrator  # backend dependency changes
docker compose up -d --build app           # frontend dependency changes

# Rebuild everything
docker compose up -d --build
```

### Viewing Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f orchestrator
docker compose logs -f app
docker compose logs -f postgres
```

### Shell Access

```bash
# Backend container (Python/bash)
docker compose exec orchestrator bash

# Frontend container (sh - alpine)
docker compose exec app sh

# Database (psql)
docker compose exec postgres psql -U tesslate_user -d tesslate_dev
```

### Database Migrations

```bash
# Apply pending migrations
docker compose exec orchestrator alembic upgrade head

# Create a new migration
docker compose exec orchestrator alembic revision --autogenerate -m "description"

# Rollback one migration
docker compose exec orchestrator alembic downgrade -1
```

### Reset Database Only

```bash
# Stop services
docker compose down

# Remove only the database volume
docker volume rm tesslate-postgres-dev-data

# Restart (fresh database, auto-migrated)
docker compose up -d
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Host Machine (Docker Desktop)                           │
│                                                         │
│  ┌──────────────┐                                      │
│  │   Traefik     │ :80 (HTTP), :443 (HTTPS), :8080     │
│  │   (Reverse    │ Routes by path:                      │
│  │    Proxy)     │   /api/* /ws/* → orchestrator:8000   │
│  └──────┬───────┘   /*           → app:5173            │
│         │                                               │
│    ┌────┴─────┬──────────────┐                         │
│    │          │              │                          │
│    ↓          ↓              ↓                          │
│  ┌─────┐  ┌────────────┐  ┌──────────────┐            │
│  │ App │  │Orchestrator│  │User Projects │            │
│  │:5173│  │   :8000    │  │(Dynamic)     │            │
│  └─────┘  └─────┬──────┘  └──────────────┘            │
│                  │                                      │
│                  ↓                                      │
│           ┌──────────┐                                 │
│           │PostgreSQL│                                 │
│           │  :5432   │                                 │
│           └──────────┘                                 │
└─────────────────────────────────────────────────────────┘
```

### Routing Rules (Traefik)

| Path | Destination | Priority |
|------|-------------|----------|
| `/api/*` | `orchestrator:8000` | 100 |
| `/ws/*` | `orchestrator:8000` | 100 |
| `/traefik` | Traefik dashboard | 200 |
| `/*` (everything else) | `app:5173` | 10 |
| `*.localhost` | User project containers | Auto-discovered |

### Volume Mounts (Hot Reload)

**Orchestrator** mounts these for live code editing:
- `./orchestrator/app` → `/app/app`
- `./orchestrator/alembic` → `/app/alembic`
- `./orchestrator/alembic.ini` → `/app/alembic.ini`
- `./orchestrator/pyproject.toml` → `/app/pyproject.toml`
- `/var/run/docker.sock` → Docker CLI access (for managing user containers)

**App** mounts these for Vite HMR:
- `./app/src` → `/app/src`
- `./app/public` → `/app/public`
- `./app/index.html` → `/app/index.html`
- Config files: `vite.config.ts`, `tsconfig.json`, `tailwind.config.ts`, etc.

## Troubleshooting

### Port Already in Use

**Symptom**: `bind: address already in use`

**Fix**: Change the port in `.env`:
```bash
APP_PORT=8081        # default 80
BACKEND_PORT=8001    # default 8000
FRONTEND_PORT=5174   # default 5173
POSTGRES_PORT=5433   # default 5432
```

### Orchestrator Fails Health Check

**Symptom**: `tesslate-orchestrator` shows `unhealthy`

**Check logs**:
```bash
docker compose logs orchestrator
```

**Common causes**:
- Database not ready yet (postgres health check takes ~10s, orchestrator waits for it)
- Missing required env vars (`SECRET_KEY`, `LITELLM_API_BASE`)
- Port 8000 conflict

### Hot Reload Not Working

**Backend** (Uvicorn):
- Verify `WATCHFILES_FORCE_POLLING=true` is set (already in docker-compose.yml)
- Check logs: `docker compose logs -f orchestrator` (look for "Reloading...")

**Frontend** (Vite):
- Verify `CHOKIDAR_USEPOLLING=true` is set (already in docker-compose.yml)
- Check browser console for HMR connection errors
- Try hard refresh: Ctrl+Shift+R

### Database Connection Failed

```bash
# Check postgres is running
docker compose ps postgres

# Test connection
docker compose exec postgres pg_isready -U tesslate_user -d tesslate_dev
```

### User Project Container Not Accessible

User projects run as separate containers on `tesslate-network`:
- URL pattern: `http://{container-name}.{project-slug}.localhost`
- Check Traefik dashboard at http://localhost:8080 for registered routes
- Verify the container has the `com.tesslate.routable=true` label

### Windows-Specific: Node Symlink Issues

Docker on Windows can break Node.js symlinks in `node_modules/.bin/`. The devserver container auto-detects and fixes this on startup. If you hit module resolution errors, rebuild:

```bash
docker compose up -d --build app
```

See [symlink-fix.md](../infrastructure/docker/symlink-fix.md) for details.

### LITELLM_DEFAULT_MODELS Warning

If you see `The "LITELLM_DEFAULT_MODELS" variable is not set. Defaulting to a blank string.` — this is harmless. Set it in `.env` to suppress:

```bash
LITELLM_DEFAULT_MODELS=gpt-4o-mini
```

## Optional Configuration

### OAuth (Google/GitHub Login)

Uncomment and configure in `.env`:
```bash
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-secret
GOOGLE_OAUTH_REDIRECT_URI=http://localhost/api/auth/google/callback

GITHUB_CLIENT_ID=your-github-client-id
GITHUB_CLIENT_SECRET=your-github-secret
GITHUB_OAUTH_REDIRECT_URI=http://localhost/api/auth/github/callback
```

Without OAuth configured, only email/password login is available.

### Stripe (Payments)

```bash
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_PUBLISHABLE_KEY=pk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
```

For local webhook testing, use the Stripe CLI:
```bash
stripe listen --forward-to localhost:8000/api/webhooks/stripe
```

### PostHog (Analytics)

```bash
VITE_PUBLIC_POSTHOG_KEY=your_posthog_key
VITE_PUBLIC_POSTHOG_HOST=https://us.i.posthog.com
```

## Next Steps

- [Docker Infrastructure Details](../infrastructure/docker/README.md) — Deep dive into services, networks, volumes
- [Dockerfile Documentation](../infrastructure/docker/dockerfiles.md) — How each image is built
- [Minikube Setup](minikube-setup.md) — Test Kubernetes features locally
- [Adding Routers](adding-routers.md) — Create new API endpoints
- [Adding Agent Tools](adding-agent-tools.md) — Extend AI agent capabilities
- [Troubleshooting](troubleshooting.md) — More common issues and solutions
