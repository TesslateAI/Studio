#!/bin/bash
# =============================================================================
# Tesslate Studio - Minikube Setup Script
# =============================================================================
# This script sets up a local Minikube environment for testing the
# S3 Sandwich architecture with MinIO for S3 simulation.
#
# Prerequisites:
#   - Docker (running)
#   - minikube (installed)
#   - kubectl (installed)
#   - kustomize (optional, kubectl has built-in support)
#
# Usage:
#   ./setup.sh [--clean]
#
# Options:
#   --clean   Delete existing Minikube cluster and start fresh
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
MINIKUBE_PROFILE="tesslate"
MINIKUBE_CPUS=4
MINIKUBE_MEMORY=8192  # 8GB
MINIKUBE_DISK_SIZE="40g"
K8S_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

echo -e "${BLUE}=============================================${NC}"
echo -e "${BLUE}  Tesslate Studio - Minikube Setup${NC}"
echo -e "${BLUE}=============================================${NC}"
echo ""

# Parse arguments
CLEAN=false
for arg in "$@"; do
    case $arg in
        --clean)
            CLEAN=true
            shift
            ;;
    esac
done

# =============================================================================
# Helper Functions
# =============================================================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

wait_for_pods() {
    local namespace=$1
    local timeout=${2:-300}
    log_info "Waiting for pods in namespace '$namespace' to be ready..."

    kubectl wait --for=condition=ready pod \
        --all \
        --namespace="$namespace" \
        --timeout="${timeout}s" 2>/dev/null || {
        log_warning "Some pods may not be ready yet, continuing..."
    }
}

# =============================================================================
# Step 1: Clean up (optional)
# =============================================================================

if [ "$CLEAN" = true ]; then
    log_warning "Cleaning up existing Minikube cluster..."
    minikube delete --profile "$MINIKUBE_PROFILE" 2>/dev/null || true
fi

# =============================================================================
# Step 2: Start Minikube
# =============================================================================

if minikube status --profile "$MINIKUBE_PROFILE" 2>/dev/null | grep -q "Running"; then
    log_info "Minikube cluster '$MINIKUBE_PROFILE' is already running"
else
    log_info "Starting Minikube cluster..."
    minikube start \
        --profile "$MINIKUBE_PROFILE" \
        --cpus "$MINIKUBE_CPUS" \
        --memory "$MINIKUBE_MEMORY" \
        --disk-size "$MINIKUBE_DISK_SIZE" \
        --driver docker \
        --addons ingress \
        --addons storage-provisioner \
        --addons metrics-server

    log_success "Minikube cluster started"
fi

# Set kubectl context
kubectl config use-context "$MINIKUBE_PROFILE"
log_info "Kubectl context set to '$MINIKUBE_PROFILE'"

# =============================================================================
# Step 3: Create Namespaces
# =============================================================================

log_info "Creating namespaces..."

kubectl apply -f - <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: tesslate
  labels:
    app: tesslate
---
apiVersion: v1
kind: Namespace
metadata:
  name: minio-system
  labels:
    app: minio
EOF

log_success "Namespaces created"

# =============================================================================
# Step 4: Deploy MinIO (S3 Simulation)
# =============================================================================

log_info "Deploying MinIO for S3 simulation..."

# Apply MinIO manifests
kubectl apply -f "$K8S_DIR/base/minio/minio-namespace.yaml" 2>/dev/null || true
kubectl apply -f "$K8S_DIR/overlays/minikube/secrets/minio-credentials.yaml"
kubectl apply -f "$K8S_DIR/base/minio/minio-pvc.yaml"
kubectl apply -f "$K8S_DIR/base/minio/minio-deployment.yaml"
kubectl apply -f "$K8S_DIR/base/minio/minio-service.yaml"

# Wait for MinIO to be ready
wait_for_pods "minio-system" 120

# Create bucket initialization job
kubectl apply -f "$K8S_DIR/base/minio/minio-init-job.yaml"

log_success "MinIO deployed"

# =============================================================================
# Step 5: Apply Tesslate Secrets
# =============================================================================

log_info "Creating Tesslate secrets..."

kubectl apply -f "$K8S_DIR/overlays/minikube/secrets/postgres-secret.yaml"
kubectl apply -f "$K8S_DIR/overlays/minikube/secrets/s3-credentials.yaml"
kubectl apply -f "$K8S_DIR/overlays/minikube/secrets/app-secrets.yaml"

log_success "Secrets created"

# =============================================================================
# Step 6: Apply Storage Class
# =============================================================================

log_info "Creating storage class..."
kubectl apply -f "$K8S_DIR/overlays/minikube/storage-class.yaml"
log_success "Storage class created"

# =============================================================================
# Step 7: Deploy Application using Kustomize
# =============================================================================

log_info "Deploying Tesslate application..."

# Apply base resources with minikube overlay
kubectl apply -k "$K8S_DIR/overlays/minikube"

# Wait for deployments
wait_for_pods "tesslate" 300

log_success "Application deployed"

# =============================================================================
# Step 8: Setup Ingress
# =============================================================================

log_info "Configuring ingress..."

# Get Minikube IP
MINIKUBE_IP=$(minikube ip --profile "$MINIKUBE_PROFILE")
log_info "Minikube IP: $MINIKUBE_IP"

# Add hosts entries suggestion
echo ""
log_warning "Add the following to your /etc/hosts (or C:\\Windows\\System32\\drivers\\etc\\hosts):"
echo ""
echo "  $MINIKUBE_IP tesslate.local"
echo "  $MINIKUBE_IP api.tesslate.local"
echo "  $MINIKUBE_IP minio.tesslate.local"
echo ""

# =============================================================================
# Step 9: Print Status
# =============================================================================

echo ""
echo -e "${GREEN}=============================================${NC}"
echo -e "${GREEN}  Setup Complete!${NC}"
echo -e "${GREEN}=============================================${NC}"
echo ""
echo -e "${BLUE}Cluster Info:${NC}"
echo "  Profile:     $MINIKUBE_PROFILE"
echo "  Minikube IP: $MINIKUBE_IP"
echo ""
echo -e "${BLUE}URLs (after adding hosts entries):${NC}"
echo "  Frontend:  http://tesslate.local"
echo "  Backend:   http://api.tesslate.local"
echo "  MinIO:     http://minio.tesslate.local (admin: tesslate-admin / tesslate-secret-key-change-in-prod)"
echo ""
echo -e "${BLUE}Useful Commands:${NC}"
echo "  kubectl get pods -n tesslate           # List application pods"
echo "  kubectl get pods -n minio-system       # List MinIO pods"
echo "  kubectl logs -n tesslate -f <pod>      # View pod logs"
echo "  minikube dashboard --profile $MINIKUBE_PROFILE   # Open Kubernetes dashboard"
echo ""
echo -e "${BLUE}To access MinIO console (port-forward):${NC}"
echo "  kubectl port-forward -n minio-system svc/minio 9001:9001"
echo "  Then open: http://localhost:9001"
echo ""
