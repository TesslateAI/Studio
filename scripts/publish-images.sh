#!/bin/bash
# =============================================================================
# Publish Tesslate Docker Images to ECR
# =============================================================================
# Builds, pushes images to shared ECR repos with environment-specific tags,
# and restarts pods to pick up the new images.
#
# Usage:
#   ./scripts/publish-images.sh beta                  # All 3 images
#   ./scripts/publish-images.sh production backend    # Backend only
#   ./scripts/publish-images.sh beta frontend backend # Multiple images
#
# Images: backend, frontend, devserver
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

error()   { echo -e "${RED}Error: $1${NC}" >&2; exit 1; }
success() { echo -e "${GREEN}$1${NC}"; }
info()    { echo -e "${BLUE}$1${NC}"; }
warning() { echo -e "${YELLOW}$1${NC}"; }

# --- Config ---
ECR_ACCOUNT="<AWS_ACCOUNT_ID>"
ECR_REGION="us-east-1"
ECR_REGISTRY="${ECR_ACCOUNT}.dkr.ecr.${ECR_REGION}.amazonaws.com"
EKS_CLUSTER_PREFIX="tesslate"

# Image definitions: name -> Dockerfile path, build context
declare -A DOCKERFILES=(
  [backend]="orchestrator/Dockerfile"
  [frontend]="app/Dockerfile.prod"
  [devserver]="orchestrator/Dockerfile.devserver"
)
declare -A BUILD_CONTEXTS=(
  [backend]="orchestrator/"
  [frontend]="app/"
  [devserver]="orchestrator/"
)
declare -A K8S_LABELS=(
  [backend]="app=tesslate-backend"
  [frontend]="app=tesslate-frontend"
)
ALL_IMAGES="backend frontend devserver"

# --- Parse args ---
ENVIRONMENT="${1:-}"
shift || true
IMAGES="${*:-$ALL_IMAGES}"

# Validate environment
case "$ENVIRONMENT" in
  production|beta) ;;
  *) error "Usage: $0 {beta|production} [backend|frontend|devserver ...]" ;;
esac

# Validate image names
for img in $IMAGES; do
  case "$img" in
    backend|frontend|devserver) ;;
    *) error "Unknown image: $img. Valid: backend, frontend, devserver" ;;
  esac
done

# --- Summary ---
info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
info "Environment: $ENVIRONMENT"
info "Images:      $IMAGES"
info "Registry:    $ECR_REGISTRY"
info "Tag:         $ENVIRONMENT"
info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo

# --- ECR Login ---
info "Logging into ECR..."
aws ecr get-login-password --region "$ECR_REGION" \
  | docker login --username AWS --password-stdin "$ECR_REGISTRY" 2>/dev/null
success "ECR login successful"
echo

# --- Build & Push ---
for img in $IMAGES; do
  FULL_TAG="${ECR_REGISTRY}/tesslate-${img}:${ENVIRONMENT}"
  DOCKERFILE="${DOCKERFILES[$img]}"
  CONTEXT="${BUILD_CONTEXTS[$img]}"

  info "[$img] Building ${FULL_TAG}..."
  docker build --no-cache -t "$FULL_TAG" -f "$DOCKERFILE" "$CONTEXT"
  success "[$img] Build complete"

  info "[$img] Pushing..."
  docker push "$FULL_TAG"
  success "[$img] Push complete"
  echo
done

# --- Switch kubectl context to target cluster ---
EKS_CLUSTER="${EKS_CLUSTER_PREFIX}-${ENVIRONMENT}-eks"
info "Switching kubectl to cluster: $EKS_CLUSTER..."
aws eks update-kubeconfig --region "$ECR_REGION" --name "$EKS_CLUSTER" --alias "$EKS_CLUSTER" >/dev/null 2>&1 \
  || error "Failed to switch kubectl context. Does cluster '$EKS_CLUSTER' exist?"
success "kubectl context set to $EKS_CLUSTER"
echo

# --- Restart pods ---
info "Restarting pods on $EKS_CLUSTER..."
for img in $IMAGES; do
  LABEL="${K8S_LABELS[$img]:-}"
  if [ -n "$LABEL" ]; then
    info "[$img] Deleting pod with label $LABEL..."
    kubectl delete pod -n tesslate -l "$LABEL" 2>/dev/null || true
  fi
done

# Wait for rollouts
for img in $IMAGES; do
  LABEL="${K8S_LABELS[$img]:-}"
  if [ -n "$LABEL" ]; then
    DEPLOY_NAME="tesslate-${img}"
    info "[$img] Waiting for rollout..."
    kubectl rollout status "deployment/${DEPLOY_NAME}" -n tesslate --timeout=120s
    success "[$img] Ready"
  fi
done
echo

# --- Verify ---
info "Verifying deployment on $EKS_CLUSTER..."
kubectl get pods -n tesslate -o wide | grep -v cleanup
echo
success "Publish complete for $ENVIRONMENT on $EKS_CLUSTER!"
