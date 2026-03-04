# Docker Agent Context

Quick reference for Docker Compose development environment.

## File Locations

**Compose**: `docker-compose.yml` (project root)
**Backend Dockerfile**: `orchestrator/Dockerfile`
**Frontend Dockerfile**: `app/Dockerfile`
**Devserver Dockerfile**: `orchestrator/Dockerfile.devserver`
**Environment**: `.env` (copied from `.env.example`)

See [dockerfiles.md](dockerfiles.md) for Dockerfile details.

## From-Scratch Setup

```bash
cp .env.example .env           # configure SECRET_KEY, LITELLM_API_BASE, LITELLM_MASTER_KEY
docker compose up --build -d   # build images and start all services
docker compose ps              # verify all 4 services are healthy
```

See [Docker Setup Guide](../../guides/docker-setup.md) for full walkthrough.

## Quick Commands

```bash
# Start
docker compose up -d

# Start with rebuild
docker compose up -d --build

# Stop (keep data)
docker compose down

# Stop and wipe all data (volumes)
docker compose down --volumes

# Logs
docker compose logs -f orchestrator
docker compose logs -f app

# Rebuild single service
docker compose up -d --build orchestrator

# Shell access
docker compose exec orchestrator bash
docker compose exec app sh
docker compose exec postgres psql -U tesslate_user -d tesslate_dev

# Database migrations
docker compose exec orchestrator alembic upgrade head
```

## Clean Slate Reset

```bash
# Remove containers, volumes, and network
docker compose down --volumes --remove-orphans

# Remove all tesslate images
docker images --format "{{.Repository}}:{{.Tag}} {{.ID}}" | grep -i tesslate | awk '{print $2}' | sort -u | xargs docker rmi -f

# Rebuild from scratch
docker compose up --build -d
```

## Services & Ports

| Service | Container Name | Port | Purpose |
|---------|---------------|------|---------|
| `app` | `tesslate-app` | 5173 | Vite dev server (React frontend) |
| `orchestrator` | `tesslate-orchestrator` | 8000 | FastAPI backend |
| `postgres` | `tesslate-postgres-dev` | 5432 | PostgreSQL database |
| `traefik` | `tesslate-traefik` | 80, 443, 8080 | Reverse proxy + dashboard |
| `redis` | `tesslate-redis` | 6379 | Redis (pub/sub, task queue, cache) |
| `worker` | `tesslate-worker` | — | ARQ worker (agent task execution) |

## Access URLs

| URL | Service |
|-----|---------|
| http://localhost | Frontend via Traefik |
| http://localhost:5173 | Frontend direct |
| http://localhost/api | Backend API via Traefik |
| http://localhost:8000 | Backend API direct |
| http://localhost:8000/docs | Swagger UI |
| http://localhost:8080 | Traefik dashboard |
| `{container}.localhost` | User project containers |

## Hot Reload

**Backend**: Uvicorn watches `./orchestrator/app/` — auto-reloads on save
**Frontend**: Vite HMR watches `./app/src/` — instant browser updates
**Worker**: Same as backend — Uvicorn watches `./orchestrator/app/` via volume mount

## Volumes

| Volume | Purpose |
|--------|---------|
| `tesslate-postgres-dev-data` | PostgreSQL data (persists between restarts) |
| `tesslate-base-cache` | Pre-installed marketplace bases |
| `tesslate-projects-data` | All user project source code |
| `tesslate-redis-data` | Redis persistence data |

## Dependency Management

`node_modules` is **never** copied between filesystems. When a project is created from a base template, generated directories (`node_modules`, `.next`, `__pycache__`, `.venv`, `dist`, `build`) are skipped during the file copy. The container installs dependencies on first boot using the lockfile-detected package manager (bun → pnpm → yarn → npm).

See [symlink-fix.md](symlink-fix.md) for full details.

## When to Load This Context

- Setting up Docker Compose for the first time
- Debugging Docker service issues
- Adding new services to docker-compose.yml
- Troubleshooting hot reload or volume issues
