#!/bin/bash
# =============================================================================
# Tesslate Studio - Minikube Teardown Script
# =============================================================================
# This script cleans up the Minikube environment.
#
# Usage:
#   ./teardown.sh [--all]
#
# Options:
#   --all   Delete the entire Minikube cluster (not just resources)
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

echo -e "${BLUE}=============================================${NC}"
echo -e "${BLUE}  Tesslate Studio - Minikube Teardown${NC}"
echo -e "${BLUE}=============================================${NC}"
echo ""

# Parse arguments
DELETE_CLUSTER=false
for arg in "$@"; do
    case $arg in
        --all)
            DELETE_CLUSTER=true
            shift
            ;;
    esac
done

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

if [ "$DELETE_CLUSTER" = true ]; then
    log_warning "Deleting entire Minikube cluster..."
    minikube delete --profile "$MINIKUBE_PROFILE"
    log_success "Minikube cluster deleted"
else
    log_info "Deleting Tesslate resources..."

    # Delete application resources
    kubectl delete namespace tesslate --ignore-not-found=true
    kubectl delete namespace minio-system --ignore-not-found=true

    # Delete storage class
    kubectl delete storageclass tesslate-block-storage --ignore-not-found=true

    log_success "Resources deleted"
    log_info "Minikube cluster is still running. Use --all to delete it."
fi

echo ""
echo -e "${GREEN}Teardown complete!${NC}"
