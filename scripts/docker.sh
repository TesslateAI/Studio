#!/usr/bin/env bash
# Tesslate Studio - Docker Compose Management
# Usage: scripts/docker.sh <command> [options]
#
# Commands:
#   start            Start all services (auto-starts Colima on macOS)
#   stop             Stop services (keep volumes)
#   down [--volumes] Stop + remove containers (--volumes removes data too)
#   restart [svc]    Restart all or a specific service
#   rebuild [svc]    Rebuild image(s) and restart (--no-cache for fresh build)
#   logs [svc]       Tail service logs
#   migrate          Run Alembic database migrations
#   status           Show service health and URLs
#   shell [svc]      Open interactive shell (default: backend)
#   reset            Full clean slate: down, remove images, rebuild, start, migrate

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

# Service short name -> docker compose service name
resolve_svc() {
  local name="${1:-}"
  case "$name" in
    backend)   echo "orchestrator" ;;
    frontend)  echo "app" ;;
    worker)    echo "worker" ;;
    postgres)  echo "postgres" ;;
    redis)     echo "redis" ;;
    traefik)   echo "traefik" ;;
    devserver) echo "devserver" ;;
    "")        echo "" ;;
    *)         echo "$name" ;;  # pass through if already a compose name
  esac
}

# Service compose name -> container name (for docker exec)
resolve_container() {
  local svc="${1:-orchestrator}"
  case "$svc" in
    orchestrator) echo "tesslate-orchestrator" ;;
    app)          echo "tesslate-app" ;;
    worker)       echo "tesslate-worker" ;;
    postgres)     echo "tesslate-postgres-dev" ;;
    redis)        echo "tesslate-redis" ;;
    traefik)      echo "tesslate-traefik" ;;
    *)            echo "tesslate-$svc" ;;
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

ensure_env() {
  if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    error ".env file not found. Run: cp .env.example .env"
    exit 1
  fi
}

check_prereqs() {
  ensure_docker
  ensure_env
}

cmd_start() {
  header "Starting Tesslate Studio (Docker Compose)"

  # Auto-start Colima on macOS if not running
  if [[ "$(uname -s)" == "Darwin" ]] && command -v colima &>/dev/null; then
    if ! colima status 2>/dev/null | grep -q "Running"; then
      info "Starting Colima..."
      colima start --cpu 4 --memory 8 --disk 60
      success "Colima started"
    fi
  fi

  check_prereqs

  # Ensure traefik acme.json exists
  mkdir -p "$PROJECT_ROOT/traefik"
  if [[ ! -f "$PROJECT_ROOT/traefik/acme.json" ]]; then
    touch "$PROJECT_ROOT/traefik/acme.json"
    chmod 600 "$PROJECT_ROOT/traefik/acme.json" 2>/dev/null || true
  fi

  # Ensure devserver image exists
  if ! docker image inspect tesslate-devserver:latest &>/dev/null; then
    info "Building devserver image (first time)..."
    docker build -t tesslate-devserver:latest \
      -f orchestrator/Dockerfile.devserver .
    success "Devserver image built"
  fi

  docker compose up -d

  info "Waiting for services to be healthy..."
  local retries=30
  while (( retries > 0 )); do
    if docker exec tesslate-orchestrator curl -sf http://localhost:8000/health &>/dev/null; then
      break
    fi
    sleep 2
    (( retries-- ))
  done

  success "All services started"
  _print_docker_urls
}

cmd_stop() {
  check_prereqs
  info "Stopping services..."
  docker compose stop
  success "Services stopped"
}

cmd_down() {
  check_prereqs
  if [[ "${1:-}" == "--volumes" ]]; then
    warn "Removing all volumes (database data will be lost)"
    docker compose down --volumes --remove-orphans
  else
    docker compose down
  fi
  success "Services removed"
}

cmd_restart() {
  check_prereqs
  local svc
  svc=$(resolve_svc "${1:-}")
  if [[ -n "$svc" ]]; then
    info "Restarting $svc..."
    docker compose restart "$svc"
  else
    info "Restarting all services..."
    docker compose restart
  fi
  success "Restart complete"
}

cmd_rebuild() {
  check_prereqs
  local svc
  svc=$(resolve_svc "${1:-}")
  local cache_flag=""

  # Check for --no-cache in args
  for arg in "$@"; do
    [[ "$arg" == "--no-cache" ]] && cache_flag="--no-cache"
  done

  if [[ -n "$svc" && "$svc" != "--no-cache" ]]; then
    info "Rebuilding $svc..."
    docker compose build $cache_flag "$svc"
    docker compose up -d "$svc"
    # If backend rebuilt, also restart worker (same image)
    if [[ "$svc" == "orchestrator" ]]; then
      info "Restarting worker (shares backend image)..."
      docker compose restart worker
    fi
  else
    info "Rebuilding all services..."
    docker compose build $cache_flag
    docker compose up -d
  fi
  success "Rebuild complete"
}

cmd_logs() {
  check_prereqs
  local svc
  svc=$(resolve_svc "${1:-}")
  if [[ -n "$svc" ]]; then
    docker compose logs -f "$svc"
  else
    docker compose logs -f
  fi
}

cmd_status() {
  check_prereqs
  header "Service Status"
  docker compose ps
  echo ""
  _print_docker_urls
}

cmd_shell() {
  check_prereqs
  local svc
  svc=$(resolve_svc "${1:-backend}")
  local container
  container=$(resolve_container "$svc")
  info "Opening shell in $container..."
  docker exec -it "$container" /bin/bash
}

cmd_migrate() {
  check_prereqs
  info "Running Alembic migrations..."
  docker exec tesslate-orchestrator alembic upgrade head
  success "Migrations complete"
}


cmd_reset() {
  check_prereqs
  warn "This will destroy ALL data and rebuild from scratch."
  read -rp "Are you sure? (y/N) " confirm
  [[ "$confirm" =~ ^[Yy]$ ]] || { info "Aborted."; return; }

  header "Resetting Tesslate Studio"

  info "Removing containers and volumes..."
  docker compose down --volumes --remove-orphans

  info "Removing Tesslate images..."
  docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' \
    | grep -i tesslate \
    | awk '{print $2}' \
    | sort -u \
    | xargs docker rmi -f 2>/dev/null || true

  info "Rebuilding..."
  docker compose build

  info "Building devserver image..."
  docker build -t tesslate-devserver:latest \
    -f orchestrator/Dockerfile.devserver .

  cmd_start
  cmd_migrate

  success "Reset complete"
}

_print_docker_urls() {
  header "Access URLs"
  echo "  Frontend:        http://localhost"
  echo "  Backend API:     http://localhost:8000"
  echo "  API Docs:        http://localhost:8000/docs"
  echo "  Traefik:         http://traefik.localhost:8080"
}

_usage() {
  echo "Usage: $(basename "$0") <command> [options]"
  echo ""
  echo "Commands:"
  echo "  start            Start all services"
  echo "  stop             Stop services (keep volumes)"
  echo "  down [--volumes] Stop + remove containers"
  echo "  restart [svc]    Restart all or a specific service"
  echo "  rebuild [svc]    Rebuild + restart (--no-cache for fresh build)"
  echo "  logs [svc]       Tail service logs"
  echo "  migrate          Run Alembic database migrations"
  echo "  status           Show service health and URLs"
  echo "  shell [svc]      Open interactive shell (default: backend)"
  echo "  reset            Full clean slate rebuild"
  echo ""
  echo "Services: backend, frontend, worker, postgres, redis, traefik"
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
