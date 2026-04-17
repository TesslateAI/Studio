#!/usr/bin/env bash
# Build external app images, roll the minikube backend, and seed all 7 apps.
#
# Prereqs: docker (with Docker Desktop WSL integration enabled), kubectl,
# minikube profile `tesslate` running.
#
# Usage:
#   scripts/seed_all_apps.sh [--skip-build] [--skip-rollout] [--skip-seed]
#
# Environment:
#   LLAMA_API_KEY    if set, the llama-api-credentials secret is created/updated
#                    from this value. If unset, the script prints the command
#                    and moves on (seeding still works for apps that don't
#                    need the key).

set -euo pipefail

CTX=tesslate
NS=tesslate
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

SKIP_BUILD=${SKIP_BUILD:-0}
SKIP_ROLLOUT=${SKIP_ROLLOUT:-0}
SKIP_SEED=${SKIP_SEED:-0}

for arg in "$@"; do
  case "$arg" in
    --skip-build)   SKIP_BUILD=1 ;;
    --skip-rollout) SKIP_ROLLOUT=1 ;;
    --skip-seed)    SKIP_SEED=1 ;;
    -h|--help)
      grep -E '^#( |$)' "$0" | sed 's/^# //; s/^#$//'
      exit 0
      ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mXX %s\033[0m\n' "$*"; exit 1; }

for bin in docker kubectl minikube; do
  command -v "$bin" >/dev/null 2>&1 || die "$bin not on PATH"
done

say "minikube profile check"
minikube -p "$CTX" status | head -5

# ────────────────────────────────────────────────────────────────────────────
# 1. Build custom images into minikube's docker daemon + preload MiroFish.
# ────────────────────────────────────────────────────────────────────────────
if [[ "$SKIP_BUILD" != 1 ]]; then
  say "point docker at minikube"
  eval "$(minikube -p "$CTX" docker-env)"

  say "rebuild tesslate-frontend:latest (picks up new AppWorkspacePage)"
  docker build -t tesslate-frontend:latest -f "$REPO_ROOT/app/Dockerfile.prod" "$REPO_ROOT/app/"

  say "rebuild tesslate-backend:latest (picks up config.py + new seed_apps.py)"
  docker build -t tesslate-backend:latest -f "$REPO_ROOT/orchestrator/Dockerfile" "$REPO_ROOT/orchestrator/"

  say "build tesslate-markitdown:latest"
  docker build -t tesslate-markitdown:latest "$REPO_ROOT/seeds/apps/markitdown/"

  if [[ -d "$REPO_ROOT/seeds/apps/deer-flow" ]]; then
    say "build tesslate-deerflow:latest (heavy, ~5-10 min)"
    docker build -t tesslate-deerflow:latest "$REPO_ROOT/seeds/apps/deer-flow/" || \
      warn "deer-flow build failed — app will be published but install will fail until fixed"
  fi

  # MiroFish: pull the upstream image and load it into minikube's node cache.
  say "load ghcr.io/666ghj/mirofish:latest into minikube"
  docker pull ghcr.io/666ghj/mirofish:latest || warn "mirofish pull failed"
  # Already in minikube's daemon since we eval'd docker-env; nothing else to do.

  say "current minikube images (filtered)"
  docker images | grep -E 'tesslate-|mirofish' || true
else
  say "SKIP_BUILD=1 — skipping image builds"
fi

# ────────────────────────────────────────────────────────────────────────────
# 2. Ensure the llama-api-credentials secret exists (shared by crm-demo,
#    nightly-digest, deer-flow, mirofish).
# ────────────────────────────────────────────────────────────────────────────
if [[ -n "${LLAMA_API_KEY:-}" ]]; then
  say "upsert llama-api-credentials secret in $NS"
  kubectl --context="$CTX" -n "$NS" create secret generic llama-api-credentials \
    --from-literal=api_key="$LLAMA_API_KEY" \
    --dry-run=client -o yaml | kubectl --context="$CTX" -n "$NS" apply -f -
else
  if ! kubectl --context="$CTX" -n "$NS" get secret llama-api-credentials >/dev/null 2>&1; then
    warn "llama-api-credentials not present in $NS namespace and LLAMA_API_KEY not set"
    warn "apps that need Llama (crm-demo, nightly-digest, deer-flow, mirofish) will fail to start"
    warn "to fix later:"
    warn "  kubectl --context=$CTX -n $NS create secret generic llama-api-credentials \\"
    warn "    --from-literal=api_key='<your-key>'"
  fi
fi

# ────────────────────────────────────────────────────────────────────────────
# 3. Roll the backend so TSL_APPS_DEV_AUTO_APPROVE + bumped project caps
#    are picked up.
# ────────────────────────────────────────────────────────────────────────────
if [[ "$SKIP_ROLLOUT" != 1 ]]; then
  say "apply minikube overlay"
  kubectl --context="$CTX" apply -k "$REPO_ROOT/k8s/overlays/minikube/"

  say "roll backend + worker"
  kubectl --context="$CTX" -n "$NS" rollout restart deploy/tesslate-backend deploy/tesslate-worker
  kubectl --context="$CTX" -n "$NS" rollout status  deploy/tesslate-backend --timeout=180s
  kubectl --context="$CTX" -n "$NS" rollout status  deploy/tesslate-worker --timeout=180s

  say "verify TSL_APPS_DEV_AUTO_APPROVE=1"
  kubectl --context="$CTX" -n "$NS" exec deploy/tesslate-backend -- printenv TSL_APPS_DEV_AUTO_APPROVE || \
    warn "TSL_APPS_DEV_AUTO_APPROVE not set — apps will publish as pending"
else
  say "SKIP_ROLLOUT=1 — skipping backend roll"
fi

# ────────────────────────────────────────────────────────────────────────────
# 4. Seed all 7 apps via the unified runner.
# ────────────────────────────────────────────────────────────────────────────
if [[ "$SKIP_SEED" != 1 ]]; then
  say "seed apps (unified runner)"
  kubectl --context="$CTX" -n "$NS" exec deploy/tesslate-backend -- \
    env TSL_APPS_DEV_AUTO_APPROVE=1 python -m scripts.seed_apps || \
    warn "unified runner reported failures — check per-app logs above"
else
  say "SKIP_SEED=1 — skipping seed step"
fi

say "done. Visit /apps on your minikube frontend to see the tiles."
