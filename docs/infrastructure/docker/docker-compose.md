# Docker Compose Configuration

Detailed documentation of docker-compose.yml services.

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/docker-compose.yml`

## Services

### traefik
- Reverse proxy routing *.localhost
- Ports: 80 (HTTP), 443 (HTTPS), 8080 (Dashboard)
- Auto-discovers containers with label `com.tesslate.traefik=main`
- Dashboard: http://localhost:8080

### postgres
- PostgreSQL 15 Alpine
- Port: 5432 (exposed for external tools)
- Volume: `postgres-dev-data` (persisted)
- Health check: `pg_isready`

### orchestrator
- FastAPI backend
- Port: 8000 (exposed)
- Hot reload: Watches `./orchestrator/app/`
- Volume mounts: app/, users/, /var/run/docker.sock
- Env: `DEPLOYMENT_MODE=docker`

### app
- React + Vite frontend
- Port: 5173 (Vite dev server)
- Hot module replacement enabled
- Volume mounts: src/, public/, config files

## Networks

**tesslate-network**: Main network for all services
**Project networks**: Created on-demand (tesslate-{project-slug})

## Volumes

**postgres-dev-data**: Database persistence
**base-cache**: Marketplace templates
**projects-data**: User project files (shared)

## Environment Variables

Create `.env` file:

```
# Required
SECRET_KEY=xxx
LITELLM_API_BASE=https://your-litellm.com
LITELLM_MASTER_KEY=xxx
LITELLM_DEFAULT_MODELS=claude-sonnet-4.6,claude-opus-4.6

# Database
POSTGRES_PASSWORD=dev_password_change_me

# Optional
APP_PORT=80
BACKEND_PORT=8000
FRONTEND_PORT=5173
```

See `.env.example` for full list.

## Health Checks

All services have health checks for proper startup ordering:
- postgres: `pg_isready`
- orchestrator: `curl /health`
- app: `wget /`
