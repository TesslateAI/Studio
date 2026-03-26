#!/usr/bin/env bash
# Tesslate Studio - Minikube Management (Swiss Knife)
# Usage: scripts/minikube.sh <command> [options]
#
# Setup:
#   init               Generate secret files from examples (run first)
#
# Lifecycle:
#   start              Start minikube cluster and deploy all services
#   stop               Stop minikube (preserves state)
#   down               Delete minikube cluster entirely
#   reset              Full teardown: delete cluster, rebuild, redeploy
#
# Deploy:
#   deploy-k8s         Reapply app manifests and restart pods
#   deploy-compute     Reapply btrfs-CSI + Volume Hub manifests
#   rebuild <svc>      Rebuild image, load into minikube, restart pod
#   rebuild --all      Rebuild all images (backend, frontend, devserver, btrfs-csi)
#   restart [svc]      Restart pod(s) for a service
#
# Operations:
#   migrate            Run Alembic database migrations
#   seed               Seed database with marketplace data
#   logs [svc]         Tail pod logs for a service
#   shell [svc]        Open interactive shell in pod (default: backend)
#   status             Show cluster state and URLs
#   tunnel             Start minikube tunnel (foreground, blocks)
#   test [name]        Run integration tests (s3-sandwich|pod-affinity)
#
# Cloudflare Tunnel (optional):
#   cf start           Deploy cloudflared tunnel connector
#   cf stop            Remove tunnel connector
#   cf status          Show tunnel connector status
#   cf logs            Tail cloudflared logs

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; }
header()  { echo -e "\n${BOLD}$*${NC}"; }

PROFILE="tesslate"
NAMESPACE="tesslate"

# Configurable via env vars (e.g., MINIKUBE_DRIVER=docker, MINIKUBE_MEMORY=6144)
MINIKUBE_CPUS="${MINIKUBE_CPUS:-4}"
MINIKUBE_MEMORY="${MINIKUBE_MEMORY:-8192}"
# MINIKUBE_DRIVER — leave unset to auto-detect (OrbStack, Docker Desktop, etc.)

# Service short name -> K8s deployment name
resolve_k8s() {
  local name="${1:-backend}"
  case "$name" in
    backend)  echo "tesslate-backend" ;;
    frontend) echo "tesslate-frontend" ;;
    worker)   echo "tesslate-worker" ;;
    postgres) echo "postgres" ;;
    redis)    echo "redis" ;;
    *)        echo "$name" ;;
  esac
}

# Service short name -> pod label
resolve_label() {
  local name="${1:-backend}"
  case "$name" in
    backend)  echo "tesslate-backend" ;;
    frontend) echo "tesslate-frontend" ;;
    worker)   echo "tesslate-worker" ;;
    postgres) echo "postgres" ;;
    redis)    echo "redis" ;;
    *)        echo "$name" ;;
  esac
}

# Image build config
image_name() {
  case "$1" in
    backend)   echo "tesslate-backend" ;;
    frontend)  echo "tesslate-frontend" ;;
    devserver) echo "tesslate-devserver" ;;
    btrfs-csi) echo "tesslate-btrfs-csi" ;;
    *) echo "" ;;
  esac
}

image_dockerfile() {
  case "$1" in
    backend)   echo "orchestrator/Dockerfile" ;;
    frontend)  echo "app/Dockerfile.prod" ;;
    devserver) echo "orchestrator/Dockerfile.devserver" ;;
    btrfs-csi) echo "services/btrfs-csi/Dockerfile" ;;
  esac
}

image_context() {
  case "$1" in
    backend)   echo "orchestrator" ;;
    frontend)  echo "app" ;;
    devserver) echo "orchestrator" ;;
    btrfs-csi) echo "services/btrfs-csi" ;;
  esac
}

ensure_docker() {
  if ! docker info &>/dev/null; then
    error "Docker daemon is not reachable. Start your Docker runtime (OrbStack, Docker Desktop, etc.)."
    exit 1
  fi
}

ensure_minikube() {
  if ! minikube status -p "$PROFILE" 2>/dev/null | grep -q "Running"; then
    error "Minikube cluster '$PROFILE' is not running."
    echo "  Run: scripts/minikube.sh start"
    exit 1
  fi
}

wait_for_rollout() {
  local deployment="$1"
  local timeout="${2:-120}"
  info "Waiting for $deployment to be ready..."
  kubectl rollout status "deployment/$deployment" -n "$NAMESPACE" --timeout="${timeout}s"
}

wait_for_backend_ready() {
  info "Waiting for backend pod to be ready..."
  kubectl wait --for=condition=ready pod \
    -l app=tesslate-backend \
    -n "$NAMESPACE" \
    --timeout=120s
}

# Build image and load into minikube.
# Uses Docker layer cache by default. Pass --no-cache as $2 to bust cache.
build_and_load() {
  local svc="$1"
  local cache_flag="${2:-}"
  local img
  img="$(image_name "$svc"):latest"
  local dockerfile
  dockerfile=$(image_dockerfile "$svc")
  local context
  context=$(image_context "$svc")

  if [[ "$cache_flag" == "--no-cache" ]]; then
    info "Rebuilding $img (no cache)..."
    minikube -p "$PROFILE" ssh -- docker rmi -f "$img" 2>/dev/null || true
    docker rmi -f "$img" 2>/dev/null || true
  else
    info "Building $img (cached)..."
  fi

  docker build $cache_flag -t "$img" -f "$dockerfile" "$context"

  info "Loading $img into minikube..."
  minikube -p "$PROFILE" image load "$img"
  success "$img built and loaded"
}

# ── Init (secret generation) ──────────────────────────────────────────

# All secret files that must exist before 'start' can run.
# Format: "source_example_path:destination_path:short_label"
STACK_SECRETS=(
  "k8s/overlays/minikube/secrets/postgres-secret.example.yaml:k8s/overlays/minikube/secrets/postgres-secret.yaml:postgres-secret"
  "k8s/overlays/minikube/secrets/s3-credentials.example.yaml:k8s/overlays/minikube/secrets/s3-credentials.yaml:s3-credentials"
  "k8s/overlays/minikube/secrets/app-secrets.example.yaml:k8s/overlays/minikube/secrets/app-secrets.yaml:app-secrets"
  "k8s/overlays/minikube/minio/credentials.example.yaml:k8s/overlays/minikube/minio/credentials.yaml:minio-credentials"
  "services/btrfs-csi/overlays/minikube/csi-credentials.example.yaml:services/btrfs-csi/overlays/minikube/csi-credentials.yaml:csi-credentials"
)

# Generate secret files from examples. Returns number of NEW files created.
_init_secrets() {
  local -n entries=$1
  local created=0
  local skipped=0

  for entry in "${entries[@]}"; do
    IFS=':' read -r src dst label <<< "$entry"
    if [[ -f "$PROJECT_ROOT/$dst" ]]; then
      skipped=$((skipped + 1))
    elif [[ -f "$PROJECT_ROOT/$src" ]]; then
      cp "$PROJECT_ROOT/$src" "$PROJECT_ROOT/$dst"
      warn "Created $label → $dst"
      created=$((created + 1))
    else
      error "Example file not found: $src"
      exit 1
    fi
  done

  if [[ $created -eq 0 ]]; then
    info "All secret files already exist ($skipped skipped)"
  else
    echo ""
    warn "$created file(s) created from examples. Edit them with your values before running 'start'."
  fi
  return $created
}

# Validate that all secrets exist and none contain obvious placeholders.
_ensure_secrets() {
  local -n entries=$1
  local missing=()

  for entry in "${entries[@]}"; do
    IFS=':' read -r _ dst label <<< "$entry"
    if [[ ! -f "$PROJECT_ROOT/$dst" ]]; then
      missing+=("$label ($dst)")
    fi
  done

  if [[ ${#missing[@]} -gt 0 ]]; then
    error "Missing secret files. Run 'scripts/minikube.sh init' first."
    for m in "${missing[@]}"; do
      echo "  - $m"
    done
    exit 1
  fi
}

cmd_init() {
  header "Initializing Tesslate Studio secrets"
  _init_secrets STACK_SECRETS

  echo ""
  info "Files to edit:"
  echo "  k8s/overlays/minikube/secrets/app-secrets.yaml        (LiteLLM, OAuth, Stripe, domain)"
  echo "  k8s/overlays/minikube/secrets/postgres-secret.yaml    (database password)"
  echo "  k8s/overlays/minikube/secrets/s3-credentials.yaml     (S3/MinIO keys)"
  echo "  k8s/overlays/minikube/minio/credentials.yaml          (MinIO root password)"
  echo "  services/btrfs-csi/overlays/minikube/csi-credentials.yaml  (CSI S3 config)"
  echo ""
  info "Then run: scripts/minikube.sh start"
}

cmd_start() {
  header "Starting Tesslate Studio (Minikube)"

  ensure_docker

  # Validate secrets exist (no auto-copy — user must run 'init' first)
  _ensure_secrets STACK_SECRETS

  # Start or resume minikube (driver auto-detected or set via MINIKUBE_DRIVER)
  if minikube status -p "$PROFILE" 2>/dev/null | grep -q "Running"; then
    info "Minikube cluster '$PROFILE' is already running"
  else
    local driver_flag=""
    if [[ -n "${MINIKUBE_DRIVER:-}" ]]; then
      driver_flag="--driver=$MINIKUBE_DRIVER"
    fi

    info "Starting minikube cluster..."
    minikube start \
      -p "$PROFILE" \
      $driver_flag \
      --cpus="$MINIKUBE_CPUS" \
      --memory="$MINIKUBE_MEMORY" \
      --disk-size=40g \
      --addons ingress \
      --addons storage-provisioner \
      --addons metrics-server
    success "Minikube cluster started"
  fi

  # Ensure all images are loaded (app + infrastructure)
  for svc in backend frontend devserver btrfs-csi; do
    local img
    img="$(image_name "$svc"):latest"
    if ! minikube -p "$PROFILE" ssh -- docker image inspect "$img" &>/dev/null 2>&1; then
      warn "Image $img not found in minikube. Building..."
      build_and_load "$svc"
    fi
  done

  # ── Deploy manifests in dependency order ──────────────────────────────
  # Each layer is a standalone kustomization — no inline YAML or patching.
  # Order matters: MinIO must be ready before CSI (CSI syncs to MinIO on startup).

  # 1. Cluster-scoped prereqs (StorageClass + VolumeSnapshot CRDs)
  header "Applying cluster prereqs"
  kubectl apply -f k8s/overlays/minikube/storage-class.yaml
  kubectl apply -k k8s/overlays/minikube/snapshot-crds --server-side 2>/dev/null \
    || kubectl apply -k k8s/overlays/minikube/snapshot-crds

  # 2. MinIO (minio-system namespace — S3 simulation for local dev)
  #    Must be ready before CSI since btrfs-csi syncs snapshots to MinIO.
  header "Applying MinIO"
  kubectl apply -k k8s/overlays/minikube/minio
  info "Waiting for MinIO..."
  kubectl rollout status deployment/minio -n minio-system --timeout=120s
  info "Waiting for MinIO init job (bucket creation)..."
  kubectl wait --for=condition=complete job/minio-init -n minio-system --timeout=120s

  # 3. btrfs-CSI driver + Volume Hub (kube-system namespace)
  header "Applying btrfs-CSI + Volume Hub"
  kubectl apply -k services/btrfs-csi/overlays/minikube
  info "Waiting for Volume Hub..."
  kubectl rollout status deployment/tesslate-volume-hub -n kube-system --timeout=120s
  info "Waiting for CSI node..."
  kubectl rollout status daemonset/tesslate-btrfs-csi-node -n kube-system --timeout=180s

  # 4. Compute pool namespace + isolation (tesslate-compute-pool)
  header "Applying Compute Pool"
  kubectl apply -k k8s/base/compute-pool

  # 5. Main application (tesslate namespace)
  header "Applying Tesslate application"
  kubectl apply -k k8s/overlays/minikube

  # ── Wait for critical deployments ─────────────────────────────────────
  header "Waiting for services"
  wait_for_rollout "postgres" 120
  wait_for_rollout "tesslate-backend" 180
  wait_for_rollout "tesslate-frontend" 120

  success "All services deployed"
  echo ""
  warn "Start the tunnel in a separate terminal:"
  echo "  scripts/minikube.sh tunnel"
  echo ""
  _print_mk_urls
}

cmd_stop() {
  info "Stopping minikube cluster..."
  minikube stop -p "$PROFILE"
  success "Cluster stopped (state preserved)"
}

cmd_down() {
  warn "This will delete the entire minikube cluster and all data."
  read -rp "Are you sure? (y/N) " confirm
  [[ "$confirm" =~ ^[Yy]$ ]] || { info "Aborted."; return; }

  minikube delete -p "$PROFILE"
  success "Cluster deleted"
}

cmd_tunnel() {
  info "Starting minikube tunnel (Ctrl+C to stop)..."
  echo "  This enables http://localhost access to cluster services."
  minikube tunnel -p "$PROFILE"
}

cmd_restart() {
  ensure_docker
  ensure_minikube
  local name="${1:-}"

  if [[ -z "$name" ]]; then
    info "Restarting all pods..."
    kubectl delete pod -n "$NAMESPACE" --all
    wait_for_rollout "tesslate-backend" 180
    wait_for_rollout "tesslate-frontend" 120
  else
    local label
    label=$(resolve_label "$name")
    info "Restarting $name pods..."
    kubectl delete pod -n "$NAMESPACE" -l "app=$label"

    local deploy
    deploy=$(resolve_k8s "$name")
    wait_for_rollout "$deploy" 120

    # If backend, also restart worker (same image)
    if [[ "$name" == "backend" ]]; then
      info "Also restarting worker (shares backend image)..."
      kubectl delete pod -n "$NAMESPACE" -l app=tesslate-worker
      wait_for_rollout "tesslate-worker" 120
    fi
  fi
  success "Restart complete"
}

cmd_rebuild() {
  ensure_docker
  ensure_minikube

  local target=""
  local cache_flag=""
  for arg in "$@"; do
    case "$arg" in
      --no-cache) cache_flag="--no-cache" ;;
      *)          target="$arg" ;;
    esac
  done

  if [[ "$target" == "--all" ]]; then
    for svc in backend frontend devserver btrfs-csi; do
      build_and_load "$svc" "$cache_flag"
    done
    info "Restarting all pods..."
    kubectl delete pod -n "$NAMESPACE" --all
    kubectl delete pod -n kube-system -l app=tesslate-volume-hub
    kubectl delete pod -n kube-system -l app=tesslate-btrfs-csi-node
    wait_for_rollout "tesslate-backend" 180
    wait_for_rollout "tesslate-frontend" 120
    kubectl rollout status deployment/tesslate-volume-hub -n kube-system --timeout=120s
    kubectl rollout status daemonset/tesslate-btrfs-csi-node -n kube-system --timeout=120s
    success "Full rebuild complete"
    return
  fi

  if [[ -z "$target" ]]; then
    error "Usage: minikube.sh rebuild <backend|frontend|devserver|btrfs-csi|--all> [--no-cache]"
    exit 1
  fi

  local img
  img=$(image_name "$target")
  if [[ -z "$img" ]]; then
    error "No image build config for '$target'. Use: backend, frontend, devserver, btrfs-csi, --all"
    exit 1
  fi

  build_and_load "$target" "$cache_flag"

  # Restart relevant pods
  if [[ "$target" == "devserver" ]]; then
    success "Devserver image rebuilt and loaded (no pods to restart)"
  elif [[ "$target" == "btrfs-csi" ]]; then
    kubectl delete pod -n kube-system -l app=tesslate-volume-hub
    kubectl delete pod -n kube-system -l app=tesslate-btrfs-csi-node
    kubectl rollout status deployment/tesslate-volume-hub -n kube-system --timeout=120s
    kubectl rollout status daemonset/tesslate-btrfs-csi-node -n kube-system --timeout=120s
    success "btrfs-csi pods restarted"
  else
    local label
    label=$(resolve_label "$target")
    kubectl delete pod -n "$NAMESPACE" -l "app=$label"

    local deploy
    deploy=$(resolve_k8s "$target")
    wait_for_rollout "$deploy" 120

    if [[ "$target" == "backend" ]]; then
      info "Also restarting worker..."
      kubectl delete pod -n "$NAMESPACE" -l app=tesslate-worker
      wait_for_rollout "tesslate-worker" 120
    fi
  fi
  success "Rebuild complete"
}

cmd_logs() {
  ensure_minikube
  local name="${1:-backend}"
  local deploy
  deploy=$(resolve_k8s "$name")
  kubectl logs -f -n "$NAMESPACE" "deployment/$deploy"
}

cmd_status() {
  ensure_minikube
  header "Application Pods ($NAMESPACE)"
  kubectl get pods -n "$NAMESPACE" -o wide
  echo ""
  header "Storage Pods (kube-system)"
  kubectl get pods -n kube-system -l 'app in (tesslate-btrfs-csi-node,tesslate-volume-hub)' -o wide 2>/dev/null \
    || echo "  No storage pods found"
  echo ""
  header "Ingress"
  kubectl get ingress -n "$NAMESPACE" 2>/dev/null || echo "  No ingress found"
  echo ""
  _print_mk_urls
}

cmd_shell() {
  ensure_minikube
  local name="${1:-backend}"
  local deploy
  deploy=$(resolve_k8s "$name")
  info "Opening shell in $deploy..."
  kubectl exec -it -n "$NAMESPACE" "deployment/$deploy" -- /bin/bash
}

cmd_migrate() {
  ensure_minikube
  wait_for_backend_ready
  info "Running Alembic migrations..."
  kubectl exec -n "$NAMESPACE" deployment/tesslate-backend -- alembic upgrade head
  success "Migrations complete"
}


cmd_seed() {
  ensure_minikube
  wait_for_backend_ready

  header "Seeding database"
  local backend_pod
  backend_pod=$(kubectl get pods -n "$NAMESPACE" -l app=tesslate-backend -o jsonpath='{.items[0].metadata.name}')
  if [[ -z "$backend_pod" ]]; then
    error "No backend pod found"
    exit 1
  fi

  local seed_dir="$PROJECT_ROOT/scripts/seed"
  if [[ ! -d "$seed_dir" ]]; then
    error "Seed directory not found: $seed_dir"
    exit 1
  fi

  local scripts=(
    seed_marketplace_bases.py
    seed_marketplace_agents.py
    seed_opensource_agents.py
    seed_skills.py
    seed_themes.py
    seed_mcp_servers.py
    seed_community_bases.py
  )

  for script in "${scripts[@]}"; do
    if [[ -f "$seed_dir/$script" ]]; then
      info "Running $script..."
      kubectl cp "$seed_dir/$script" "$NAMESPACE/${backend_pod}:/tmp/$script"
      kubectl exec -n "$NAMESPACE" "$backend_pod" -- python "/tmp/$script" 2>&1 || {
        warn "$script failed (non-fatal), continuing..."
      }
    fi
  done

  success "Database seeded"
}

cmd_deploy_compute() {
  ensure_docker
  ensure_minikube

  header "Deploying compute stack (btrfs-CSI + Volume Hub)"

  # Ensure btrfs-csi image is loaded
  local img="tesslate-btrfs-csi:latest"
  if ! minikube -p "$PROFILE" ssh -- docker image inspect "$img" &>/dev/null 2>&1; then
    warn "Image $img not found in minikube. Building..."
    build_and_load "btrfs-csi"
  fi

  # VolumeSnapshot CRDs
  info "Applying VolumeSnapshot CRDs..."
  kubectl apply -k k8s/overlays/minikube/snapshot-crds --server-side 2>/dev/null \
    || kubectl apply -k k8s/overlays/minikube/snapshot-crds

  # btrfs-CSI + Volume Hub
  info "Applying btrfs-CSI + Volume Hub manifests..."
  kubectl apply -k services/btrfs-csi/overlays/minikube

  info "Waiting for Volume Hub..."
  kubectl rollout status deployment/tesslate-volume-hub -n kube-system --timeout=120s
  info "Waiting for CSI node..."
  kubectl rollout status daemonset/tesslate-btrfs-csi-node -n kube-system --timeout=120s

  success "Compute stack deployed"
  echo ""
  info "Verify: kubectl get pods -n kube-system -l 'app in (tesslate-btrfs-csi-node,tesslate-volume-hub)'"
}

cmd_deploy_k8s() {
  ensure_minikube

  header "Applying application manifests"
  kubectl apply -k k8s/overlays/minikube
  success "Manifests applied"

  info "Restarting pods..."
  kubectl rollout restart deployment/tesslate-backend -n "$NAMESPACE"
  kubectl rollout restart deployment/tesslate-frontend -n "$NAMESPACE"
  kubectl rollout restart deployment/tesslate-worker -n "$NAMESPACE"

  wait_for_rollout "tesslate-backend" 180
  wait_for_rollout "tesslate-frontend" 120
  wait_for_rollout "tesslate-worker" 120

  success "Application redeployed"
}

cmd_test() {
  ensure_minikube
  local name="${1:-}"
  local test_dir="$PROJECT_ROOT/k8s/scripts/minikube"

  if [[ -z "$name" ]]; then
    echo "Available tests:"
    echo "  s3-sandwich     Test S3 Sandwich storage pattern"
    echo "  pod-affinity    Test multi-container pod scheduling"
    echo ""
    echo "Usage: $(basename "$0") test <name>"
    return
  fi

  case "$name" in
    s3-sandwich)
      if [[ ! -f "$test_dir/test-s3-sandwich.sh" ]]; then
        error "Test script not found: $test_dir/test-s3-sandwich.sh"
        exit 1
      fi
      header "Running S3 Sandwich test"
      bash "$test_dir/test-s3-sandwich.sh"
      ;;
    pod-affinity)
      if [[ ! -f "$test_dir/test-pod-affinity.sh" ]]; then
        error "Test script not found: $test_dir/test-pod-affinity.sh"
        exit 1
      fi
      header "Running Pod Affinity test"
      bash "$test_dir/test-pod-affinity.sh"
      ;;
    *)
      error "Unknown test: $name. Available: s3-sandwich, pod-affinity"
      exit 1
      ;;
  esac
}

cmd_reset() {
  warn "This will delete the entire cluster and rebuild from scratch."
  read -rp "Are you sure? (y/N) " confirm
  [[ "$confirm" =~ ^[Yy]$ ]] || { info "Aborted."; return; }

  header "Resetting Tesslate Studio (Minikube)"
  minikube delete -p "$PROFILE" 2>/dev/null || true

  cmd_start
  cmd_migrate

  success "Reset complete"
}

# ── Cloudflare Tunnel (optional addon) ─────────────────────────────────

cmd_cf() {
  local subcmd="${1:-}"
  shift || true

  case "$subcmd" in
    init)   cmd_cf_init "$@" ;;
    start)  cmd_cf_start "$@" ;;
    stop)   cmd_cf_stop "$@" ;;
    status) cmd_cf_status "$@" ;;
    logs)   cmd_cf_logs "$@" ;;
    *)
      echo "Usage: $(basename "$0") cf <init|start|stop|status|logs>"
      echo ""
      echo "Cloudflare Tunnel (optional addon):"
      echo "  cf init     Generate credentials file (run first)"
      echo "  cf start    Deploy cloudflared connector"
      echo "  cf stop     Remove cloudflared connector"
      echo "  cf status   Show tunnel pod status"
      echo "  cf logs     Tail cloudflared logs"
      ;;
  esac
}

CF_SECRETS=(
  "k8s/overlays/minikube/cloudflare-tunnel/credentials.example.yaml:k8s/overlays/minikube/cloudflare-tunnel/credentials.yaml:cloudflare-tunnel"
)

cmd_cf_init() {
  header "Initializing Cloudflare Tunnel credentials"
  _init_secrets CF_SECRETS

  echo ""
  info "Step 1: Cloudflare Dashboard"
  echo "  1. Go to https://one.dash.cloudflare.com → Networks → Tunnels"
  echo "  2. Create a tunnel, copy the token"
  echo "  3. Paste the token into: k8s/overlays/minikube/cloudflare-tunnel/credentials.yaml"
  echo "  4. Add a public hostname in the tunnel config:"
  echo "       Type: HTTP"
  echo "       URL:  ingress-nginx-controller.ingress-nginx.svc.cluster.local:80"
  echo "       HTTP Host Header: localhost"
  echo ""
  info "Step 2: Update app-secrets for your tunnel domain"
  echo "  Edit: k8s/overlays/minikube/secrets/app-secrets.yaml"
  echo ""
  echo "  APP_DOMAIN:          \"your-tunnel-domain.com\""
  echo "  APP_BASE_URL:        \"https://your-tunnel-domain.com\""
  echo "  DEV_SERVER_BASE_URL: \"https://your-tunnel-domain.com\""
  echo "  CORS_ORIGINS:        \"http://localhost,https://your-tunnel-domain.com\""
  echo "  ALLOWED_HOSTS:       \"localhost,your-tunnel-domain.com\""
  echo "  COOKIE_DOMAIN:       \"\"  (empty — works for any domain)"
  echo "  COOKIE_SECURE:       \"true\"  (CF tunnel uses HTTPS)"
  echo ""
  warn "After editing secrets, restart the backend: scripts/minikube.sh restart backend"
  echo ""
  info "Then run: scripts/minikube.sh cf start"
}

cmd_cf_start() {
  ensure_docker
  ensure_minikube

  header "Starting Cloudflare Tunnel"

  # Validate credentials exist (no auto-copy — user must run 'cf init' first)
  _ensure_secrets CF_SECRETS

  # Check that the token has been changed from the placeholder
  local cf_dir="$PROJECT_ROOT/k8s/overlays/minikube/cloudflare-tunnel"
  if grep -q "your-tunnel-token-here" "$cf_dir/credentials.yaml"; then
    error "Tunnel token is still the placeholder value."
    echo "  Edit: k8s/overlays/minikube/cloudflare-tunnel/credentials.yaml"
    exit 1
  fi

  # Verify ingress-nginx is running (cloudflared routes through it)
  if ! kubectl get service ingress-nginx-controller -n ingress-nginx &>/dev/null; then
    error "ingress-nginx is not deployed. Ensure minikube was started with --addons ingress."
    echo "  Run: minikube addons enable ingress -p $PROFILE"
    exit 1
  fi

  # Apply manifests
  kubectl apply -k k8s/overlays/minikube/cloudflare-tunnel
  info "Waiting for cloudflared..."
  kubectl rollout status deployment/cloudflared -n cloudflare-tunnel --timeout=60s

  success "Cloudflare Tunnel is running"
  echo ""
  info "Ensure your Cloudflare dashboard route points to:"
  echo "  Service URL:    http://ingress-nginx-controller.ingress-nginx.svc.cluster.local:80"
  echo "  Host Header:    localhost"
}

cmd_cf_stop() {
  ensure_minikube

  header "Stopping Cloudflare Tunnel"

  if kubectl get namespace cloudflare-tunnel &>/dev/null; then
    kubectl delete -k k8s/overlays/minikube/cloudflare-tunnel
    success "Cloudflare Tunnel removed"
  else
    info "Cloudflare Tunnel is not deployed"
  fi
}

cmd_cf_status() {
  ensure_minikube

  header "Cloudflare Tunnel Status"

  if ! kubectl get namespace cloudflare-tunnel &>/dev/null; then
    info "Cloudflare Tunnel is not deployed"
    echo "  Run: scripts/minikube.sh cf start"
    return
  fi

  kubectl get pods -n cloudflare-tunnel -o wide
  echo ""

  # Show pod readiness
  local ready
  ready=$(kubectl get pods -n cloudflare-tunnel -l app=cloudflared -o jsonpath='{.items[0].status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "Unknown")
  if [[ "$ready" == "True" ]]; then
    success "Tunnel connector is healthy"
  else
    warn "Tunnel connector is not ready (status: $ready)"
  fi
}

cmd_cf_logs() {
  ensure_minikube

  if ! kubectl get namespace cloudflare-tunnel &>/dev/null; then
    error "Cloudflare Tunnel is not deployed"
    echo "  Run: scripts/minikube.sh cf start"
    exit 1
  fi

  kubectl logs -f -n cloudflare-tunnel deployment/cloudflared
}

_print_mk_urls() {
  header "Access URLs"
  echo "  Frontend:        http://localhost"
  echo "  Backend API:     http://localhost/api"
  echo "  API Docs:        http://localhost/api/docs"
  echo ""
  echo "  Requires tunnel: scripts/minikube.sh tunnel"
}

_usage() {
  echo "Usage: $(basename "$0") <command> [options]"
  echo ""
  echo "Setup:"
  echo "  init               Generate secret files from examples (run first)"
  echo ""
  echo "Lifecycle:"
  echo "  start              Start minikube cluster and deploy all services"
  echo "  stop               Stop cluster (preserves state)"
  echo "  down               Delete cluster entirely"
  echo "  reset              Full teardown + rebuild from scratch"
  echo ""
  echo "Deploy:"
  echo "  deploy-k8s         Reapply app manifests and restart pods"
  echo "  deploy-compute     Reapply btrfs-CSI + Volume Hub manifests"
  echo "  rebuild <svc>      Rebuild image, load, restart (backend|frontend|devserver|btrfs-csi|--all)"
  echo "  restart [svc]      Restart pod(s) for a service"
  echo ""
  echo "Operations:"
  echo "  migrate            Run Alembic database migrations"
  echo "  seed               Seed database with marketplace data"
  echo "  logs [svc]         Tail pod logs (default: backend)"
  echo "  shell [svc]        Open shell in pod (default: backend)"
  echo "  status             Show cluster state and URLs"
  echo "  tunnel             Start minikube tunnel (foreground)"
  echo "  test [name]        Run integration tests (s3-sandwich|pod-affinity)"
  echo ""
  echo "Cloudflare Tunnel (optional):"
  echo "  cf init            Generate tunnel credentials file"
  echo "  cf start           Deploy cloudflared tunnel connector"
  echo "  cf stop            Remove tunnel connector"
  echo "  cf status          Show tunnel status"
  echo "  cf logs            Tail cloudflared logs"
  echo ""
  echo "Services: backend, frontend, worker, postgres, redis, devserver, btrfs-csi"
}

main() {
  local cmd="${1:-}"
  shift || true

  case "$cmd" in
    init)           cmd_init "$@" ;;
    start)          cmd_start "$@" ;;
    stop)           cmd_stop "$@" ;;
    down)           cmd_down "$@" ;;
    restart)        cmd_restart "$@" ;;
    rebuild)        cmd_rebuild "$@" ;;
    deploy-k8s)     cmd_deploy_k8s "$@" ;;
    deploy-compute) cmd_deploy_compute "$@" ;;
    seed)           cmd_seed "$@" ;;
    logs)           cmd_logs "$@" ;;
    migrate)        cmd_migrate "$@" ;;
    status)         cmd_status "$@" ;;
    shell)          cmd_shell "$@" ;;
    tunnel)         cmd_tunnel "$@" ;;
    test)           cmd_test "$@" ;;
    reset)          cmd_reset "$@" ;;
    cf)             cmd_cf "$@" ;;
    --help|-h|"")   _usage ;;
    *)
      error "Unknown command: $cmd"
      _usage
      exit 1
      ;;
  esac
}

main "$@"
