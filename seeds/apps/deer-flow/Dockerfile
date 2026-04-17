# Tesslate-ified DeerFlow image — backend + frontend in a single container.
#
# Upstream: https://github.com/bytedance/deer-flow
# The upstream prod setup runs 4 containers (nginx + frontend + gateway +
# langgraph). We collapse it to one process group via `make dev` for seed
# purposes. This is heavy (Python 3.12 + Node 22 + uv + pnpm, plus the
# cloned repo and its deps) — expect a ~2GB image and a several-minute build.

FROM python:3.12-slim-bookworm

ARG DEER_FLOW_REF=main
ENV DEER_FLOW_REF=${DEER_FLOW_REF} \
    DEBIAN_FRONTEND=noninteractive \
    NODE_MAJOR=22 \
    PNPM_HOME=/root/.local/share/pnpm \
    PATH=/root/.local/share/pnpm:/root/.local/bin:/usr/local/bin:/usr/bin:/bin

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl git ca-certificates gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
       | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
       > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# uv + pnpm
COPY --from=ghcr.io/astral-sh/uv:0.7.20 /uv /uvx /usr/local/bin/
RUN npm install -g pnpm@10

# Clone upstream at build time. Pinned via DEER_FLOW_REF so rebuilds are reproducible.
RUN git clone --depth 1 --branch "${DEER_FLOW_REF}" https://github.com/bytedance/deer-flow.git /app
WORKDIR /app

# Install dependencies (backend via uv, frontend via pnpm).
RUN cd backend && uv sync --frozen
RUN cd frontend && pnpm install --frozen-lockfile

# Ship a bare config.yaml template. The app reads LLM creds from env;
# $LLM_API_KEY / $LLM_BASE_URL are materialized by Tesslate's env_resolver
# at container-start time via the manifest.
COPY config.yaml /app/backend/config.yaml

EXPOSE 3000 8001 2024

# `make dev` boots backend + frontend + langgraph in dev mode with hot reload.
# The frontend serves on :3000, which we expose as the primary UI surface.
CMD ["make", "dev"]
