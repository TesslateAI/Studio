#!/usr/bin/env bash
# Tesslate Studio - Minikube/Kubernetes Management
# Usage: scripts/minikube.sh <command> [options]
#
# Commands:
#   start            Start minikube cluster and deploy services
#   stop             Stop minikube (preserves state)
#   down             Delete minikube cluster entirely
#   restart [svc]    Restart pod(s) for a service
#   rebuild <svc>    Rebuild image, load into minikube, restart pod
#   rebuild --all    Rebuild all images (backend, frontend, devserver)
#   logs [svc]       Tail pod logs for a service
#   migrate          Run Alembic database migrations
#   status           Show cluster state and URLs
#   shell [svc]      Open interactive shell in pod (default: backend)
#   tunnel           Start minikube tunnel (foreground, blocks)
#   reset            Full teardown: delete cluster, rebuild, redeploy

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
    *) echo "" ;;
  esac
}

image_dockerfile() {
  case "$1" in
    backend)   echo "orchestrator/Dockerfile" ;;
    frontend)  echo "app/Dockerfile.prod" ;;
    devserver) echo "orchestrator/Dockerfile.devserver" ;;
  esac
}

image_context() {
  case "$1" in
    backend)   echo "orchestrator" ;;
    frontend)  echo "app" ;;
    devserver) echo "orchestrator" ;;
  esac
}

ensure_docker() {
  if ! docker info &>/dev/null; then
    error "Docker daemon is not reachable."
    if [[ "$(uname -s)" == "Darwin" ]]; then
      echo "  Run: colima start --cpu 4 --memory 8 --disk 60"
    fi
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

  # Auto-start Colima on macOS
  if [[ "$(uname -s)" == "Darwin" ]] && command -v colima &>/dev/null; then
    if ! colima status 2>/dev/null | grep -q "Running"; then
      info "Starting Colima..."
      colima start --cpu 4 --memory 8 --disk 60
      success "Colima started"
    fi
  fi

  ensure_docker

  # Start or resume minikube
  if minikube status -p "$PROFILE" 2>/dev/null | grep -q "Running"; then
    info "Minikube cluster '$PROFILE' is already running"
  else
    info "Starting minikube cluster..."
    minikube start \
      -p "$PROFILE" \
      --driver=docker \
      --cpus=2 \
      --memory=4096 \
      --disk-size=40g \
      --addons ingress \
      --addons storage-provisioner \
      --addons metrics-server
    success "Minikube cluster started"
  fi

  # Ensure images are loaded
  for svc in backend frontend devserver; do
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

  # Apply manifests
  info "Applying Kubernetes manifests..."
  kubectl apply -k k8s/overlays/minikube

  # Wait for critical deployments
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
    for svc in backend frontend devserver; do
      rebuild_image "$svc"
    done
    info "Restarting all pods..."
    kubectl delete pod -n "$NAMESPACE" --all
    wait_for_rollout "tesslate-backend" 180
    wait_for_rollout "tesslate-frontend" 120
    success "Full rebuild complete"
    return
  fi

  if [[ -z "$target" ]]; then
    error "Usage: minikube.sh rebuild <backend|frontend|devserver|--all>"
    exit 1
  fi

  local img
  img=$(image_name "$target")
  if [[ -z "$img" ]]; then
    error "No image build config for '$target'. Use: backend, frontend, devserver, --all"
    exit 1
  fi

  rebuild_image "$target"

  # Restart relevant pods
  if [[ "$target" == "devserver" ]]; then
    success "Devserver image rebuilt and loaded (no pods to restart)"
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
  header "Pod Status"
  kubectl get pods -n "$NAMESPACE" -o wide
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
  echo "Commands:"
  echo "  start            Start minikube cluster and deploy"
  echo "  stop             Stop cluster (preserves state)"
  echo "  down             Delete cluster entirely"
  echo "  restart [svc]    Restart pod(s) for a service"
  echo "  rebuild <svc>    Rebuild image, load, restart (backend|frontend|devserver|--all)"
  echo "  logs [svc]       Tail pod logs (default: backend)"
  echo "  migrate          Run Alembic migrations"
  echo "  status           Show cluster state and URLs"
  echo "  shell [svc]      Open shell in pod (default: backend)"
  echo "  tunnel           Start minikube tunnel"
  echo "  reset            Full teardown + rebuild from scratch"
  echo ""
  echo "Services: backend, frontend, worker, postgres, redis, devserver"
}

main() {
  local cmd="${1:-}"
  shift || true

  case "$cmd" in
    start)   cmd_start "$@" ;;
    stop)    cmd_stop "$@" ;;
    down)    cmd_down "$@" ;;
    restart) cmd_restart "$@" ;;
    rebuild) cmd_rebuild "$@" ;;
    logs)    cmd_logs "$@" ;;
    migrate) cmd_migrate "$@" ;;
    status)  cmd_status "$@" ;;
    shell)   cmd_shell "$@" ;;
    tunnel)  cmd_tunnel "$@" ;;
    reset)   cmd_reset "$@" ;;
    --help|-h|"")  _usage ;;
    *)
      error "Unknown command: $cmd"
      _usage
      exit 1
      ;;
  esac
}

main "$@"
