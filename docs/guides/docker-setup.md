# Running OpenSail on Docker

Complete walk-through to get OpenSail running locally with Docker Compose. A fresh clone should be at `http://localhost` with a logged-in user and a working project in under 20 minutes.

If you just need commands, jump to [Quick Start](#quick-start). If something breaks, jump to [Common Issues](#common-issues).

## 1. Prerequisites

| Tool | Minimum | Notes |
|------|---------|-------|
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | 4.30+ (Engine 26+, Compose v2) | Required on macOS, Windows, and Linux desktops. Enable WSL 2 backend on Windows. |
| `docker compose` | v2.27+ | Ships with Docker Desktop. The guide uses the `docker compose` (no hyphen) form. |
| `git` | 2.40+ | For cloning the repo. |
| Disk | 15 GB free | Images: roughly 2.5 GB. Named volumes (Postgres, projects, base cache, Redis) grow with use. |
| RAM | 8 GB minimum, 16 GB recommended | Orchestrator plus worker plus gateway plus user containers get heavy. |
| CPU | 4 cores | Vite HMR and agent runs are CPU sensitive. |

Node.js and Python are NOT required on the host. Everything runs inside containers.

### OS support

| OS | Status | Notes |
|----|--------|-------|
| macOS 13+ (Intel or Apple Silicon) | Supported | Docker Desktop with the Virtualization.framework backend. Apple Silicon pulls `arm64` images transparently. |
| Windows 11 + WSL 2 | Supported | Run the commands from inside your WSL 2 distro, not PowerShell. Docker Desktop must have "Use WSL 2 based engine" on. |
| Linux (Ubuntu 22.04+, Fedora 39+, Arch) | Supported | Install Docker Engine plus the Compose plugin. Rootless Docker works but see [Platform notes](#platform-notes). |
| macOS + Colima | Supported with tweaks | See [Platform notes](#platform-notes). |
| Native Windows (no WSL) | Not supported | Path translation breaks the bind mounts. |

## 2. Clone and configure

```bash
git clone https://github.com/TesslateAI/tesslate-studio.git
cd tesslate-studio
cp .env.example .env
```

Open `.env` in your editor. Only two values are genuinely required for first boot; everything else has sensible defaults.

### Required env vars

| Variable | Why | How to get one |
|----------|-----|----------------|
| `SECRET_KEY` | Signs JWTs and derives other secrets. | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `LITELLM_API_BASE` and `LITELLM_MASTER_KEY` | Backend routes LLM calls through a LiteLLM proxy. Without a real endpoint the agent features stay disabled, but the app still boots. | Point at your existing proxy, or stand up your own (`docs/infrastructure/kubernetes/litellm.md`). |

### Env var groups (optional)

These live in `/home/smirk/Tesslate-Studio/.env.example`. Open that file for the full list; the groups below are the ones you are most likely to touch.

| Group | Vars | When to set |
|-------|------|-------------|
| Database | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT` | Keep defaults for dev. Change `POSTGRES_PORT` only if `5432` is busy. |
| Redis | `REDIS_URL`, `REDIS_PORT` | Default `redis://redis:6379/0` works in Compose. |
| Secrets | `SECRET_KEY`, `INTERNAL_API_SECRET`, `CSRF_SECRET_KEY`, `DEPLOYMENT_ENCRYPTION_KEY`, `CHANNEL_ENCRYPTION_KEY` | Generate real values for any environment you share. `CHANNEL_ENCRYPTION_KEY` needs a Fernet key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. |
| LiteLLM | `LITELLM_API_BASE`, `LITELLM_MASTER_KEY`, `LITELLM_DEFAULT_MODELS`, `LITELLM_TEAM_ID`, `LITELLM_INITIAL_BUDGET` | Required for the agent. `LITELLM_DEFAULT_MODELS` is a comma list, no spaces. |
| OAuth (optional) | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`, `GITHUB_*` | Enable social login. Without these only email/password works. Redirect URI for dev: `http://localhost/api/auth/{google,github}/callback`. |
| Domain and ports | `APP_DOMAIN`, `APP_PROTOCOL`, `APP_PORT`, `APP_SECURE_PORT`, `BACKEND_PORT`, `FRONTEND_PORT`, `TRAEFIK_DASHBOARD_PORT` | Keep `APP_DOMAIN=localhost` for dev. Change individual ports only on conflicts. |
| Stripe (optional) | `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_*_PRICE_ID` | Needed for billing UI. Use `sk_test_*` keys plus `stripe listen` for webhooks. |
| SMTP (optional) | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SENDER_EMAIL`, `TWO_FA_ENABLED` | Required if you want 2FA codes or password resets by email. |

Docker Compose does not interpolate variables inside other variables in `.env`, so `ALLOWED_HOSTS=${APP_DOMAIN}` keeps the literal `${APP_DOMAIN}` string. For dev it still works because `APP_DOMAIN=localhost` is also the default; in production set `ALLOWED_HOSTS` to an explicit value.

## 3. First boot

```bash
docker compose up --build -d
```

This builds the orchestrator image and the app image from source, pulls Postgres, Redis, and Traefik, and brings up seven services. First build takes 3 to 6 minutes depending on your machine. Subsequent boots are near-instant thanks to the build cache.

### Services

| Service | Built from / image | Role |
|---------|-------------------|------|
| `traefik` | `traefik:v3.6` | Reverse proxy. Routes paths to the app or orchestrator and exposes `*.localhost` for user projects. |
| `postgres` | `postgres:15-alpine` | Primary database. |
| `redis` | `redis:7-alpine` | Pub/sub, ARQ task queue, distributed locks. |
| `orchestrator` | `orchestrator/Dockerfile` | FastAPI backend. Mounts `/var/run/docker.sock` so it can spawn user containers. |
| `worker` | Same image as `orchestrator`, `arq app.worker.WorkerSettings` | Runs agent tasks off the ARQ queue. |
| `gateway` | Same image as `orchestrator`, `python -m app.gateway` | Persistent connections for Telegram, Slack, Discord, WhatsApp. Idle unless you enable channels. |
| `app` | `app/Dockerfile` | Vite dev server with HMR. |
| `devserver` | `orchestrator/Dockerfile.devserver`, `entrypoint: true` | Build-only image. Never starts; produces `tesslate-devserver:latest` that user project containers derive from. |

### Verify

```bash
docker compose ps
```

Healthy output looks like this (timings will vary):

```
NAME                    STATUS
tesslate-app            Up 30s (healthy)
tesslate-gateway        Up 28s
tesslate-orchestrator   Up 40s (healthy)
tesslate-postgres-dev   Up 45s (healthy)
tesslate-redis          Up 45s (healthy)
tesslate-traefik        Up 45s
tesslate-worker         Up 40s
```

`orchestrator` can show `health: starting` for up to 30 seconds while Alembic migrations run. If it never turns `healthy`, see [Common Issues](#common-issues).

Tail the orchestrator log until you see `Uvicorn running on http://0.0.0.0:8000`:

```bash
docker compose logs -f orchestrator
```

## 4. Seed the database

On backend startup the orchestrator automatically runs `run_all_seeds()` from `/home/smirk/Tesslate-Studio/orchestrator/app/seeds/__init__.py`. That covers themes, bases, agents, skills, MCP servers, and deployment targets on a clean database. Confirm with:

```bash
docker compose exec postgres psql -U tesslate_user -d tesslate_dev -c "SELECT COUNT(*) FROM marketplace_agents;"
```

If the count is zero (older database or partial seed), re-run them manually in this order. Each script is idempotent.

```bash
# Copy the scripts into the container once
docker cp scripts/seed/. tesslate-orchestrator:/tmp/seed/

# Run them in dependency order
docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed/seed_themes.py
docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed/seed_marketplace_bases.py
docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed/seed_community_bases.py
docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed/seed_marketplace_agents.py
docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed/seed_opensource_agents.py
docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed/seed_skills.py
docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed/seed_mcp_servers.py
docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed/seed_deployment_targets.py
```

On Windows (Git Bash or MSYS2), prefix each `docker exec` with `MSYS_NO_PATHCONV=1` so paths like `/tmp/seed/...` are not translated.

What you get: themes (default-dark, default-light, midnight, ocean, forest, rose, sunset), official and open-source agents (Librarian, ReAct, Stream Builder, etc.), marketplace bases (Next.js, Vite+React+FastAPI, Vite+React+Go, Expo), open-source and Tesslate skills, MCP server catalog entries, and deployment target definitions (Vercel, Netlify, Cloudflare, Railway, etc.).

## 5. Access URLs

| Target | URL | Notes |
|--------|-----|-------|
| Frontend via Traefik | `http://localhost` | Use this for OAuth and cookie-correct testing. |
| Frontend direct | `http://localhost:5173` | Vite dev server. Bypasses Traefik. |
| Backend API via Traefik | `http://localhost/api` | Frontend calls here. |
| Backend direct | `http://localhost:8000` | Useful for `curl`. |
| OpenAPI docs | `http://localhost:8000/docs` | Swagger UI. |
| Traefik dashboard | `http://localhost:8080` | Raw dashboard. |
| Traefik via proxy | `http://localhost/traefik` | Basic-auth gated; defaults to `admin:admin`. Change `TRAEFIK_BASIC_AUTH` in `.env`. |
| PostgreSQL | `localhost:5432` | Connect with pgAdmin or DBeaver. Creds from `.env`. |
| Redis | `localhost:6379` | `redis-cli -h localhost` works. |
| User project | `http://{container}.localhost` | Wildcard is auto-handled by Traefik. Some OS require `dnsmasq` or `/etc/hosts` entries; see [Common Issues](#common-issues). |

## 6. Create your first user

You have two options.

### Option A: Sign up in the UI (recommended)

1. Visit `http://localhost`.
2. Click "Sign up", enter email and password.
3. You are logged in. Billing starts on the FREE tier.

### Option B: Create a superuser from the CLI

```bash
docker compose exec orchestrator python /app/create_superuser.py
```

The script prompts interactively for email and password. To promote an existing user to admin:

```bash
docker compose exec orchestrator python /app/make_admin.py you@example.com
```

Both scripts live at `/home/smirk/Tesslate-Studio/orchestrator/create_superuser.py` and `/home/smirk/Tesslate-Studio/orchestrator/make_admin.py`.

## 7. Create your first project

1. From the dashboard, click "New project".
2. Pick a base (for example "Vite + React + FastAPI").
3. Give it a name; a slug like `my-app-k3x8n2` is generated.
4. Wait for the toast that says "Project ready". The orchestrator copied the template and wrote a `docker-compose.yml` into `/projects/{slug}/`.
5. Click "Start". Containers for that project spin up on `tesslate-network` and register with Traefik.
6. The preview panel loads `http://frontend.localhost` (or whatever the base's primary container is called). Watch it come up with `docker compose logs -f orchestrator` if it stalls.

Open the chat panel and ask the agent to change something. For a complete reference of every agent tool, see `/home/smirk/Tesslate-Studio/packages/tesslate-agent/docs/DOCS.md`.

## 8. Clean slate reset

Exact sequence from the root [CLAUDE.md](/home/smirk/Tesslate-Studio/CLAUDE.md):

```bash
# 1. Stop and remove containers plus volumes
docker compose down --volumes --remove-orphans

# 2. Remove all OpenSail images
docker images --format "{{.Repository}}:{{.Tag}} {{.ID}}" \
  | grep -i tesslate \
  | awk '{print $2}' \
  | sort -u \
  | xargs -r docker rmi -f

# 3. Rebuild and start
docker compose up --build -d
```

Leave out step 2 if you only want to reset the database; step 1 already wipes `tesslate-postgres-dev-data`, `tesslate-redis-data`, `tesslate-projects-data`, `tesslate-base-cache`, and `tesslate-gateway-locks`.

To reset only the database:

```bash
docker compose down
docker volume rm tesslate-postgres-dev-data
docker compose up -d
```

## 9. Quick Start

For someone who has already read this guide once:

```bash
git clone https://github.com/TesslateAI/tesslate-studio.git
cd tesslate-studio
cp .env.example .env
# edit SECRET_KEY and LITELLM_* in .env
docker compose up --build -d
docker compose ps            # wait for healthy
open http://localhost         # macOS; xdg-open on Linux, start on Windows
```

## 10. Common Issues

### Port already in use

Symptom: `bind: address already in use` on `80`, `5432`, `6379`, `8000`, `5173`, or `8080`.

Fix: override the port in `.env`:

```bash
APP_PORT=8081        # default 80
BACKEND_PORT=8001    # default 8000
FRONTEND_PORT=5174   # default 5173
POSTGRES_PORT=5433   # default 5432
REDIS_PORT=6380      # default 6379
TRAEFIK_DASHBOARD_PORT=8090  # default 8080
```

Re-run `docker compose up -d`. Traefik dashboard moves with `APP_PORT`, so use `http://localhost:8081` if you changed it.

### Orchestrator stuck unhealthy

```bash
docker compose logs --tail 100 orchestrator
```

Usual causes:

- Postgres not ready yet: wait 15 more seconds.
- `SECRET_KEY` empty or still at the placeholder.
- `LITELLM_API_BASE` unreachable: the boot continues but the log shows warnings.
- Port 8000 busy on host: change `BACKEND_PORT`.

### `*.localhost` does not resolve

Modern Linux (systemd-resolved), macOS, and Windows with WSL 2 resolve `*.localhost` to `127.0.0.1` automatically. Some distros do not.

- Linux: add `address=/localhost/127.0.0.1` to dnsmasq, or add per-project entries to `/etc/hosts`.
- Windows native: edit `C:\Windows\System32\drivers\etc\hosts`.
- Browsers: Chrome and Firefox honor loopback for `*.localhost` without `/etc/hosts`.

### Hot reload not firing

The compose file already sets `WATCHFILES_FORCE_POLLING=true` (uvicorn), `CHOKIDAR_USEPOLLING=true`, and `WATCHPACK_POLLING=true` (Vite). If it still stops working:

- Inotify limit hit on Linux: `sudo sysctl fs.inotify.max_user_watches=524288`.
- WSL 2: make sure the repo lives inside the WSL filesystem (`~/code/...`), not `/mnt/c/...`. The `/mnt` mount does not emit file events reliably.

### Database connection failed

```bash
docker compose ps postgres
docker compose exec postgres pg_isready -U tesslate_user -d tesslate_dev
```

If the container is unhealthy: `docker compose logs postgres`. Usually a leftover volume with a mismatched password; run the clean slate reset.

### User project container not reachable

- Traefik dashboard at `http://localhost:8080` lists every router. Confirm your container is there.
- Verify the container has `com.tesslate.routable=true` (orchestrator sets this automatically from the generated compose).
- Check the container is on `tesslate-network`: `docker network inspect tesslate-network`.

### Docker socket permission denied (Linux)

The orchestrator mounts `/var/run/docker.sock`. If you run rootless Docker, the socket lives in `$XDG_RUNTIME_DIR/docker.sock` and the mount is wrong. Either run rootful Docker or edit the volume mount in `docker-compose.yml`.

### `LITELLM_DEFAULT_MODELS` is not set

Harmless if you have not configured LiteLLM. Set it in `.env` to silence:

```bash
LITELLM_DEFAULT_MODELS=claude-sonnet-4.6,claude-opus-4.6
```

### Tailing logs

```bash
docker compose logs -f                    # everything
docker compose logs -f orchestrator worker  # just the Python services
docker compose logs --tail 200 app         # Vite last 200 lines
```

## 11. Platform notes

### WSL 2 (Windows)

- Clone into the WSL filesystem, for example `~/code/tesslate-studio`. Bind mounts from `/mnt/c/...` are slow and drop file-change events.
- Run `docker compose` from inside WSL, not from PowerShell.
- When piping scripts that pass container paths (`/tmp/...`, `/app/...`) through `docker exec`, prefix with `MSYS_NO_PATHCONV=1` on Git Bash.

### macOS with Colima

Colima replaces Docker Desktop on macOS. OpenSail works, with two tweaks:

```bash
colima start --cpu 4 --memory 8 --disk 60 --mount-type virtiofs
export DOCKER_HOST="unix://$HOME/.colima/default/docker.sock"
```

virtiofs is the only mount type that keeps file-change events fast enough for Vite HMR.

### Linux rootless Docker

The orchestrator bind-mounts the Docker socket so it can manage user project containers. Under rootless Docker the socket path is `$XDG_RUNTIME_DIR/docker.sock` and the orchestrator inside the container cannot see it at `/var/run/docker.sock`. Either run rootful Docker for development, or change the volume mount in `docker-compose.yml` to the rootless socket and set `DOCKER_HOST` inside the orchestrator container. Kubernetes mode sidesteps this entirely.

### Volume permissions

On Linux, the Postgres volume is owned by UID 70 (the alpine postgres user). If you shell in as a different UID, you may see permission errors writing to `/var/lib/postgresql/data`. Do not chown the volume from the host; let the container manage it.

## 12. Where to next

- Desktop shell (Tauri) for a single-user experience: `/home/smirk/Tesslate-Studio/docs/desktop/CLAUDE.md`.
- Minikube for a local Kubernetes mirror of production: `/home/smirk/Tesslate-Studio/docs/guides/minikube-setup.md`.
- AWS EKS deployment: `/home/smirk/Tesslate-Studio/docs/guides/aws-deployment.md`.
- Compose file deep-dive (prod, Cloudflare tunnel, test): `/home/smirk/Tesslate-Studio/docs/infrastructure/docker-compose/README.md`.
- Traefik routing: `/home/smirk/Tesslate-Studio/docs/infrastructure/traefik/README.md`.
- Dockerfile and image build details: `/home/smirk/Tesslate-Studio/docs/infrastructure/docker/README.md`.
- Agent tool reference: `/home/smirk/Tesslate-Studio/packages/tesslate-agent/docs/DOCS.md`.
- Tesslate Apps (publish and install): `/home/smirk/Tesslate-Studio/docs/apps/CLAUDE.md`.
