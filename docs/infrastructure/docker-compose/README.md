# Docker Compose Files

> Every compose file at the repo root, what it runs, and when to pick it.

## Quick picker

| Goal | Command |
|------|---------|
| Local dev on my laptop | `docker compose up --build -d` (uses [docker-compose.yml](../../../docker-compose.yml)); full walk-through in [guides/docker-setup.md](../../guides/docker-setup.md) |
| Self-hosted prod on a single box | `docker compose -f docker-compose.prod.yml up -d` |
| Production fronted by Cloudflare Tunnel | `docker compose -f docker-compose.cloudflare-tunnel.yml up -d` plus `cloudflared` on the host |
| Run the pytest integration suite | `docker compose -f docker-compose.test.yml up -d` |

`.env.example` at the repo root is the source of truth for variable names. `.env.prod.example` lists the additional variables needed for the prod variants. New developers should start with [guides/docker-setup.md](../../guides/docker-setup.md).

## `docker-compose.yml` (local dev)

Services:

| Service | Image / build | Role |
|---------|---------------|------|
| `traefik` | `traefik:v3.6` | Edge proxy: dashboard at `/traefik`, HTTP + HTTPS entrypoints, Let's Encrypt HTTP challenge. |
| `postgres` | `postgres:15-alpine` | Primary relational DB. Exposed on `${POSTGRES_PORT:-5432}` for pgAdmin/DBeaver. |
| `redis` | `redis:7-alpine` | Pub/sub, streams, ARQ task queue, distributed locks. `--maxmemory 256mb --maxmemory-policy volatile-lru --appendonly yes`. |
| `orchestrator` | Built from `orchestrator/Dockerfile` | FastAPI backend. Mounts project source for hot reload, plus `/var/run/docker.sock` so it can manage user containers. |
| `worker` | Same image as orchestrator | `arq app.worker.WorkerSettings` worker for agent execution. |
| `gateway` | Same image as orchestrator | `python -m app.gateway` persistent platform connections (Telegram, Slack, Discord, WhatsApp). |
| `app` | Built from `app/Dockerfile` (dev variant) | React + Vite dev server with polling-based file watching. |
| `devserver` | Built from `orchestrator/Dockerfile.devserver` | Build-only: produces `tesslate-devserver:latest`, never started (`entrypoint: true`). |

Named volumes: `tesslate-postgres-dev-data`, `tesslate-base-cache`, `tesslate-projects-data`, `tesslate-redis-data`, `tesslate-gateway-locks`.

Network: `tesslate-network` (bridge).

Key env (full list in the file): `DEPLOYMENT_MODE=docker`, `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `LITELLM_*`, `STRIPE_*`, `S3_*`, `K8S_*` (used only when `DEPLOYMENT_MODE=kubernetes`), `SMTP_*` for 2FA.

## `docker-compose.prod.yml` (self-hosted prod)

Trimmed to Postgres, orchestrator, app, and Traefik (prod variant). Differences from dev:

- Traefik uses `traefik.prod.yml` with Cloudflare DNS challenge TLS.
- Reads only the env vars prod needs; everything is plumbed from real `.env` values (no defaults).
- Frontend builds with `app/Dockerfile.prod` and is served by the built-in static server on port 80.
- No `worker`, `gateway`, `redis`, or `devserver` services by default; add them per environment.
- Volume `tesslate-postgres-data` instead of `tesslate-postgres-dev-data`.

Needs: `POSTGRES_PASSWORD`, `SECRET_KEY`, `APP_DOMAIN`, `APP_PROTOCOL`, `TRAEFIK_BASIC_AUTH`, `CF_DNS_API_TOKEN`, all OAuth / Stripe / S3 vars.

## `docker-compose.cloudflare-tunnel.yml` (CF tunnel)

Same shape as the prod variant, but:

- Traefik reads `traefik.tunnel.yml`. No TLS: Cloudflare terminates at the edge.
- Traefik ports bind to `127.0.0.1:8080` (http) and `127.0.0.1:8081` (dashboard); `cloudflared` runs on the host and tunnels to `127.0.0.1:8080`.
- Forces `APP_PROTOCOL=https` for the orchestrator (external clients still see HTTPS).
- Skips Stripe, S3, K8s, CSRF, cookie, and deployment-provider env blocks. Layer those in if you need them.

## `docker-compose.test.yml` (integration tests)

Single service:

| Service | Image | Role |
|---------|-------|------|
| `postgres-test` | `postgres:15-alpine` | Isolated Postgres on port `5433`, db `tesslate_test`, user `tesslate_test`, password `testpass`. |

Pytest fixtures in `orchestrator/tests/` point at this DB. Separate from the dev Postgres so tests cannot touch dev data.

## Named volumes summary

| Volume | Created by | Purpose |
|--------|------------|---------|
| `tesslate-postgres-dev-data` | dev | Dev Postgres data dir. |
| `tesslate-postgres-data` | prod / tunnel | Prod Postgres data dir. |
| `tesslate-base-cache` | dev | Preinstalled marketplace base dependency cache. |
| `tesslate-projects-data` | dev | Shared project source files across orchestrator, worker, and user containers. |
| `tesslate-redis-data` | dev | Redis AOF on-disk persistence. |
| `tesslate-gateway-locks` | dev | Shared lock dir for the gateway process (`/var/run/tesslate`). |
| `test-db-data` | tests | Test Postgres data dir. |

## Related

- [docs/infrastructure/traefik/README.md](../traefik/README.md)
- [docs/infrastructure/docker/README.md](../docker/README.md) (Dockerfiles, build args, symlink fix)
- [docs/guides/docker-setup.md](../../guides/docker-setup.md): full walk-through
- [/home/smirk/Tesslate-Studio/.env.example](../../../.env.example) and [/home/smirk/Tesslate-Studio/.env.prod.example](../../../.env.prod.example)
