# Deployment Scripts

> Local dev bring-up helpers for Linux, macOS, and Windows. Covers bash, batch, PowerShell, and Python variants.

## Where to start

| Task | Script |
|------|--------|
| First-time macOS setup | `scripts/install-macos.sh` (at root, not under `deployment/`) |
| First-time Docker setup (Unix) | `scripts/deployment/setup-docker-dev.sh` |
| First-time Docker setup (Windows) | `scripts/deployment/setup-docker-dev.bat` |
| Native dev, services on the host (Unix) | `scripts/deployment/run-backend.sh` + `scripts/deployment/run-frontend.sh` in separate terminals |
| Native dev with Traefik containerized (Windows) | `scripts/deployment/start-all-with-traefik.bat` |
| Verify your `.env` is complete | `scripts/deployment/verify_env.py` (canonical; batch and PowerShell variants also exist) |
| Build the dev-server image used by user projects | `scripts/deployment/build-dev-image.sh` |

## Script details

### `build-dev-image.sh` and `.bat`

Builds `tesslate-devserver:latest`: the image user project containers run inside. Flags:

- `--push`: push to the container registry (DigitalOcean in legacy prod, ECR in current prod).
- `--no-cache`: force a full rebuild (use after dependency bumps).

Both Docker mode (local compose) and Kubernetes mode (via `K8S_DEVSERVER_IMAGE`) consume this image.

### `run-backend.sh` and `run-frontend.sh`

Straight passthroughs. Backend runs `uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` from `orchestrator/`. Frontend runs `npm run dev` from `app/`. Reads `.env` from the repo root.

### `setup-docker-dev.sh` and `.bat`

Idempotent first-run helper: checks Docker is reachable, copies `.env.example` to `.env` if needed, pulls/builds images, and brings up the compose stack. Safe to re-run after a reset.

### `start-all-with-traefik.bat` (Windows hybrid mode)

Starts the orchestrator, frontend, and any AI service natively on the host while running Traefik inside Docker. Preview containers for user projects only work if Traefik is up, so this is the recommended Windows workflow.

### `start-all.bat` (legacy)

Starts services natively without Traefik. User dev containers will not route. Kept for reference only: prefer `start-all-with-traefik.bat`.

### `verify_env.py` / `.bat` / `.ps1`

Reads `.env` (or `.env.example` if `.env` is absent) and reports missing or misconfigured required variables. The Python version is canonical because it has the most coverage and runs everywhere. Keep the batch and PowerShell variants in sync when adding new checks.

## Related

- Root-level dev helpers: `scripts/docker.sh`, `scripts/minikube.sh`, `scripts/install-macos.sh`
- Docker Compose files: [docs/infrastructure/docker-compose/CLAUDE.md](../infrastructure/docker-compose/CLAUDE.md)
- `.env.example`: [/home/smirk/Tesslate-Studio/.env.example](../../.env.example)
- `.env.prod.example`: [/home/smirk/Tesslate-Studio/.env.prod.example](../../.env.prod.example)
