#!/usr/bin/env bash
# Tesslate Studio - Minikube Management (Swiss Knife)
# Usage: scripts/minikube.sh <command> [options]
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

# Build image and load into minikube (with full cache busting)
rebuild_image() {
  local svc="$1"
  local img
  img="$(image_name "$svc"):latest"
  local dockerfile
  dockerfile=$(image_dockerfile "$svc")
  local context
  context=$(image_context "$svc")

  info "Rebuilding $img..."

  # 1. Delete from minikube's Docker daemon
  minikube -p "$PROFILE" ssh -- docker rmi -f "$img" 2>/dev/null || true

  # 2. Delete local image + rebuild with --no-cache
  docker rmi -f "$img" 2>/dev/null || true
  docker build --no-cache -t "$img" -f "$dockerfile" "$context"

  # 3. Load into minikube
  info "Loading $img into minikube..."
  minikube -p "$PROFILE" image load "$img"

  success "$img rebuilt and loaded"
}

# Build image and load without cache busting (for first-time setup)
build_and_load() {
  local svc="$1"
  local img
  img="$(image_name "$svc"):latest"
  local dockerfile
  dockerfile=$(image_dockerfile "$svc")
  local context
  context=$(image_context "$svc")

  info "Building $img..."
  docker build -t "$img" -f "$dockerfile" "$context"
  info "Loading $img into minikube..."
  minikube -p "$PROFILE" image load "$img"
  success "$img loaded"
}

cmd_start() {
  header "Starting Tesslate Studio (Minikube)"

  ensure_docker

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

  # Ensure K8s secrets exist (gitignored, must be generated from examples)
  local secrets_dir="$PROJECT_ROOT/k8s/overlays/minikube/secrets"
  for secret in postgres-secret s3-credentials app-secrets; do
    if [[ ! -f "$secrets_dir/${secret}.yaml" ]]; then
      if [[ -f "$secrets_dir/${secret}.example.yaml" ]]; then
        cp "$secrets_dir/${secret}.example.yaml" "$secrets_dir/${secret}.yaml"
        warn "Created ${secret}.yaml from example. Edit k8s/overlays/minikube/secrets/${secret}.yaml with your values."
      else
        error "Missing $secrets_dir/${secret}.yaml and no example found."
        exit 1
      fi
    fi
  done

  # MinIO credentials live alongside the minio overlay
  local minio_dir="$PROJECT_ROOT/k8s/overlays/minikube/minio"
  if [[ ! -f "$minio_dir/credentials.yaml" ]]; then
    if [[ -f "$minio_dir/credentials.example.yaml" ]]; then
      cp "$minio_dir/credentials.example.yaml" "$minio_dir/credentials.yaml"
      warn "Created minio credentials.yaml from example. Edit k8s/overlays/minikube/minio/credentials.yaml with your values."
    else
      error "Missing $minio_dir/credentials.yaml and no example found."
      exit 1
    fi
  fi

  # CSI credentials (MinIO S3 config for btrfs-csi)
  local csi_dir="$PROJECT_ROOT/services/btrfs-csi/overlays/minikube"
  if [[ ! -f "$csi_dir/csi-credentials.yaml" ]]; then
    if [[ -f "$csi_dir/csi-credentials.example.yaml" ]]; then
      cp "$csi_dir/csi-credentials.example.yaml" "$csi_dir/csi-credentials.yaml"
      warn "Created csi-credentials.yaml from example. Edit services/btrfs-csi/overlays/minikube/csi-credentials.yaml with your values."
    else
      error "Missing $csi_dir/csi-credentials.yaml and no example found."
      exit 1
    fi
  fi

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

  local target="${1:-}"

  if [[ "$target" == "--all" ]]; then
    for svc in backend frontend devserver btrfs-csi; do
      rebuild_image "$svc"
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
    error "Usage: minikube.sh rebuild <backend|frontend|devserver|btrfs-csi|--all>"
    exit 1
  fi

  local img
  img=$(image_name "$target")
  if [[ -z "$img" ]]; then
    error "No image build config for '$target'. Use: backend, frontend, devserver, btrfs-csi, --all"
    exit 1
  fi

  rebuild_image "$target"

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
  echo "Services: backend, frontend, worker, postgres, redis, devserver, btrfs-csi"
}

main() {
  local cmd="${1:-}"
  shift || true

  case "$cmd" in
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
    --help|-h|"")   _usage ;;
    *)
      error "Unknown command: $cmd"
      _usage
      exit 1
      ;;
  esac
}

main "$@"
