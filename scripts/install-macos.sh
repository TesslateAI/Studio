#!/usr/bin/env bash
# Tesslate Studio - macOS Interactive Installer
# Installs all dependencies, configures environment, builds images,
# and starts the development stack.
#
# Usage: scripts/install-macos.sh

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
header()  { echo -e "\n${BOLD}=== $* ===${NC}\n"; }

# Verify macOS
if [[ "$(uname -s)" != "Darwin" ]]; then
  error "This script is for macOS only."
  echo "  On Linux, install Docker natively and use scripts/docker.sh or scripts/minikube.sh"
  exit 1
fi

echo ""
echo -e "${BOLD}========================================${NC}"
echo -e "${BOLD}  Tesslate Studio - macOS Setup${NC}"
echo -e "${BOLD}========================================${NC}"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Homebrew + dependencies
# ---------------------------------------------------------------------------
header "Step 1: Prerequisites"

if ! command -v brew &>/dev/null; then
  warn "Homebrew is not installed."
  read -rp "Install Homebrew now? (Y/n) " ans
  if [[ "${ans:-Y}" =~ ^[Yy]$ ]]; then
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add to path for Apple Silicon
    if [[ -f /opt/homebrew/bin/brew ]]; then
      eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
    success "Homebrew installed"
  else
    error "Homebrew is required. Aborting."
    exit 1
  fi
else
  success "Homebrew found"
fi

install_if_missing() {
  local pkg="$1"
  if brew list --formula "$pkg" &>/dev/null; then
    success "$pkg already installed"
  else
    info "Installing $pkg..."
    brew install "$pkg"
    success "$pkg installed"
  fi
}

for dep in colima docker docker-compose docker-credential-helper kubectl; do
  install_if_missing "$dep"
done

# ---------------------------------------------------------------------------
# Step 2: Mode Selection
# ---------------------------------------------------------------------------
header "Step 2: Development Mode"

echo "Which development mode would you like to use?"
echo ""
echo "  [1] Docker Compose (recommended)"
echo "      Hot reload, fast startup, simple setup"
echo ""
echo "  [2] Kubernetes via Minikube"
echo "      Real K8s environment, tests production-like setup"
echo ""

while true; do
  read -rp "Select mode (1 or 2): " mode_choice
  case "$mode_choice" in
    1) DEV_MODE="docker"; break ;;
    2) DEV_MODE="kubernetes"; break ;;
    *) echo "Please enter 1 or 2." ;;
  esac
done

success "Selected: $DEV_MODE mode"

if [[ "$DEV_MODE" == "kubernetes" ]]; then
  install_if_missing minikube
fi

# ---------------------------------------------------------------------------
# Step 3: Docker Runtime (Colima)
# ---------------------------------------------------------------------------
header "Step 3: Docker Runtime (Colima)"

COLIMA_CPU=4
COLIMA_MEM=8
COLIMA_DISK=60

if colima status 2>/dev/null | grep -q "Running"; then
  info "Colima is already running"
  # Check resources (best-effort parsing)
  current_cpu=$(colima list -j 2>/dev/null | grep -o '"cpus":[0-9]*' | grep -o '[0-9]*' || echo "0")
  current_mem=$(colima list -j 2>/dev/null | grep -o '"memory":[0-9]*' | grep -o '[0-9]*' || echo "0")
  # colima reports memory in bytes; convert to GB
  if (( current_mem > 1000 )); then
    current_mem_gb=$(( current_mem / 1073741824 ))
  else
    current_mem_gb=$current_mem
  fi
  if (( current_cpu > 0 && current_cpu < COLIMA_CPU )) || (( current_mem_gb > 0 && current_mem_gb < COLIMA_MEM )); then
    warn "Colima may have insufficient resources (detected: ${current_cpu} CPUs, ${current_mem_gb}GB RAM)."
    warn "Recommended: ${COLIMA_CPU} CPUs, ${COLIMA_MEM}GB RAM."
    echo "  To resize: colima stop && colima start --cpu $COLIMA_CPU --memory $COLIMA_MEM --disk $COLIMA_DISK"
  else
    success "Colima resources look good"
  fi
else
  info "Starting Colima (${COLIMA_CPU} CPUs, ${COLIMA_MEM}GB RAM, ${COLIMA_DISK}GB disk)..."
  colima start --cpu "$COLIMA_CPU" --memory "$COLIMA_MEM" --disk "$COLIMA_DISK"
  success "Colima started"
fi

if ! docker info &>/dev/null; then
  error "Docker daemon is not reachable after starting Colima."
  exit 1
fi
success "Docker daemon is reachable"

# ---------------------------------------------------------------------------
# Step 4: Environment Configuration
# ---------------------------------------------------------------------------
header "Step 4: Environment Configuration"

if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
  cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
  success "Created .env from .env.example"
else
  info ".env already exists, keeping current version"
fi

# Generate a suggested secret key
suggested_key=$(openssl rand -hex 32 2>/dev/null || LC_ALL=C tr -dc 'a-f0-9' < /dev/urandom | head -c 64)

echo ""
echo -e "${YELLOW}Please configure your .env file with these required values:${NC}"
echo ""
echo "  SECRET_KEY          (suggested: $suggested_key)"
echo "  LITELLM_API_BASE    (your LiteLLM proxy URL)"
echo "  LITELLM_MASTER_KEY  (your LiteLLM API key)"
echo ""
echo -e "  Edit with: ${BOLD}nano .env${NC} or ${BOLD}code .env${NC}"
echo ""

# Check if values are still placeholder
needs_config=false
if grep -q "your-secret-key-here-change-this-in-production\|change-this-in-production" .env 2>/dev/null; then
  needs_config=true
fi
if grep -q "your-litellm-master-key-here" .env 2>/dev/null || grep -qE "^LITELLM_MASTER_KEY=$" .env 2>/dev/null; then
  needs_config=true
fi

if [[ "$needs_config" == "true" ]]; then
  read -rp "Press Enter when you've configured .env (or Ctrl+C to exit)... "

  if grep -q "your-secret-key-here-change-this-in-production\|change-this-in-production" .env 2>/dev/null; then
    warn "SECRET_KEY still has a placeholder value. Change it before production use."
  fi
else
  info ".env appears to be already configured"
fi

# ---------------------------------------------------------------------------
# Step 5: Build Docker Images
# ---------------------------------------------------------------------------
header "Step 5: Building Docker Images"

info "Building devserver image..."
docker build -t tesslate-devserver:latest \
  -f orchestrator/Dockerfile.devserver .
success "Devserver image built"

if [[ "$DEV_MODE" == "docker" ]]; then
  info "Building Docker Compose services..."
  docker compose build
  success "All Docker Compose images built"
else
  info "Building backend image..."
  docker build -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
  success "Backend image built"

  info "Building frontend image..."
  docker build -t tesslate-frontend:latest -f app/Dockerfile.prod app/
  success "Frontend image built"
fi

# ---------------------------------------------------------------------------
# Step 6: Start Stack
# ---------------------------------------------------------------------------
header "Step 6: Starting Development Stack"

if [[ "$DEV_MODE" == "docker" ]]; then
  # --- Docker Compose path ---

  mkdir -p "$PROJECT_ROOT/traefik"
  if [[ ! -f "$PROJECT_ROOT/traefik/acme.json" ]]; then
    touch "$PROJECT_ROOT/traefik/acme.json"
    chmod 600 "$PROJECT_ROOT/traefik/acme.json" 2>/dev/null || true
  fi

  info "Starting Docker Compose services..."
  docker compose up -d

  info "Waiting for services to be healthy..."
  retries=30
  while (( retries > 0 )); do
    if docker exec tesslate-orchestrator curl -sf http://localhost:8000/health &>/dev/null; then
      break
    fi
    sleep 2
    (( retries-- ))
  done
  success "Services are up"

  info "Running database migrations..."
  docker exec tesslate-orchestrator alembic upgrade head
  success "Migrations complete"


else
  # --- Minikube path ---

  info "Starting minikube cluster..."
  minikube start \
    -p tesslate \
    --driver=docker \
    --cpus=2 \
    --memory=4096 \
    --disk-size=40g \
    --addons ingress \
    --addons storage-provisioner \
    --addons metrics-server
  success "Minikube cluster started"

  # Load images into minikube
  for img in tesslate-backend tesslate-frontend tesslate-devserver; do
    info "Loading $img:latest into minikube..."
    minikube -p tesslate image load "$img:latest"
  done
  success "All images loaded"

  # Generate secrets from example files if they don't exist
  secrets_dir="k8s/overlays/minikube/secrets"
  for secret in postgres-secret s3-credentials app-secrets; do
    if [[ ! -f "$secrets_dir/${secret}.yaml" ]]; then
      if [[ -f "$secrets_dir/${secret}.example.yaml" ]]; then
        cp "$secrets_dir/${secret}.example.yaml" "$secrets_dir/${secret}.yaml"
        warn "Created $secrets_dir/${secret}.yaml from example. Edit with your values."
      fi
    else
      info "$secrets_dir/${secret}.yaml already exists"
    fi
  done

  # Apply manifests
  info "Applying Kubernetes manifests..."
  kubectl apply -k k8s/overlays/minikube

  # Wait for rollouts
  info "Waiting for pods to be ready..."
  kubectl rollout status deployment/postgres -n tesslate --timeout=120s
  kubectl rollout status deployment/tesslate-backend -n tesslate --timeout=180s
  kubectl rollout status deployment/tesslate-frontend -n tesslate --timeout=120s
  success "All pods ready"

  # Migrations
  info "Running database migrations..."
  kubectl wait --for=condition=ready pod -l app=tesslate-backend -n tesslate --timeout=120s
  kubectl exec -n tesslate deployment/tesslate-backend -- alembic upgrade head
  success "Migrations complete"

  # Seed
fi

# ---------------------------------------------------------------------------
# Step 7: Done!
# ---------------------------------------------------------------------------
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Setup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

if [[ "$DEV_MODE" == "docker" ]]; then
  echo -e "${BOLD}Access URLs:${NC}"
  echo "  Frontend:        http://localhost"
  echo "  Backend API:     http://localhost:8000"
  echo "  API Docs:        http://localhost:8000/docs"
  echo "  Traefik:         http://traefik.localhost:8080"
  echo ""
  echo -e "${BOLD}Management:${NC} scripts/docker.sh"
else
  echo -e "${BOLD}Access URLs:${NC}"
  echo "  Frontend:        http://localhost"
  echo "  Backend API:     http://localhost/api"
  echo "  API Docs:        http://localhost/api/docs"
  echo ""
  echo -e "${YELLOW}IMPORTANT: Start the tunnel in a separate terminal:${NC}"
  echo "  scripts/minikube.sh tunnel"
  echo ""
  echo -e "${BOLD}Management:${NC} scripts/minikube.sh"
fi

echo ""
echo -e "${BOLD}Quick Reference:${NC}"
if [[ "$DEV_MODE" == "docker" ]]; then
  echo "  scripts/docker.sh start       Start services"
  echo "  scripts/docker.sh stop        Stop services"
  echo "  scripts/docker.sh logs        Tail all logs"
  echo "  scripts/docker.sh rebuild     Rebuild + restart"
  echo "  scripts/docker.sh status      Show health + URLs"
  echo "  scripts/docker.sh shell       Shell into backend"
  echo "  scripts/docker.sh reset       Full clean slate"
else
  echo "  scripts/minikube.sh start     Start cluster + services"
  echo "  scripts/minikube.sh stop      Stop cluster"
  echo "  scripts/minikube.sh logs      Tail backend logs"
  echo "  scripts/minikube.sh rebuild   Rebuild image + restart"
  echo "  scripts/minikube.sh status    Show pods + URLs"
  echo "  scripts/minikube.sh shell     Shell into backend"
  echo "  scripts/minikube.sh tunnel    Start tunnel"
  echo "  scripts/minikube.sh reset     Full teardown + rebuild"
fi
echo ""
