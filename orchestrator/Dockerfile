# Main application. Built with build context = repo root so the Apps-primitive
# seed trees at /seeds/apps/<slug>/ are copied into the image.
FROM python:3.11-slim

WORKDIR /app

# apt deps: gcc for python wheel builds, git for project ops,
# curl/ca-certificates/gnupg for fetching the Docker CE keyring,
# docker-ce-cli for DEPLOYMENT_MODE=docker compose orchestration.
# Node is NOT installed — the AST worker runs in its own sidecar
# container (see k8s/base/core/backend-deployment.yaml).
RUN apt-get update && apt-get install -y \
    gcc \
    git \
    curl \
    ca-certificates \
    gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null \
    && apt-get update \
    && apt-get install -y docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

COPY orchestrator/pyproject.toml ./
COPY orchestrator/app ./app

RUN pip install --no-cache-dir -e .

# Orchestrator source (scripts, alembic, etc.).
COPY orchestrator/ ./

# Seed trees (Apps primitive). Lives outside orchestrator/ so large Next.js
# fixtures don't pollute every backend diff. Resolved by seed_*.py at
# /app/seeds/apps/<slug>/.
COPY seeds ./seeds

EXPOSE 8000

# Production/beta: drop --reload (dev-only flag that spawns a filesystem
# watcher subprocess and participated in the 2026-04-16 fork-race
# incident). Staying at single worker for now — moving to --workers 2
# for probe isolation requires first gating alembic migrations and the
# pubsub subscriber singleton to one worker. Tracked in issue #361.
# For local dev, override the CMD via docker-compose to get --reload.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]