#!/bin/bash
# ============================================================================
# Build Dev Container Image
# ============================================================================
# Builds the development server Docker image with pre-installed dependencies
# This image is used for user project containers in both Docker and Kubernetes
#
# Usage:
#   ./scripts/deployment/build-dev-image.sh              # Build for local Docker
#   ./scripts/deployment/build-dev-image.sh --push       # Build and push to registry
#   ./scripts/deployment/build-dev-image.sh --no-cache   # Force rebuild
# ============================================================================

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Default values
PUSH_TO_REGISTRY=false
NO_CACHE=""
BUILD_PLATFORM=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --push)
            PUSH_TO_REGISTRY=true
            shift
            ;;
        --no-cache)
            NO_CACHE="--no-cache"
            shift
            ;;
        --platform)
            BUILD_PLATFORM="--platform $2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --push         Push image to DigitalOcean Container Registry"
            echo "  --no-cache     Build without using cache"
            echo "  --platform     Specify platform (e.g., linux/amd64)"
            echo "  --help, -h     Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Error: Unknown option $1${NC}"
            exit 1
            ;;
    esac
done

# Image names
LOCAL_IMAGE="tesslate-devserver:latest"
REMOTE_IMAGE="registry.digitalocean.com/finetune/tesslate-dev-server:latest"

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}Building Tesslate Dev Server Image${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# Build the image
echo -e "${YELLOW}→ Building dev server image...${NC}"
cd "$PROJECT_ROOT/orchestrator"

docker build \
    -f Dockerfile.devserver \
    -t "$LOCAL_IMAGE" \
    $NO_CACHE \
    $BUILD_PLATFORM \
    .

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Dev server image built successfully: $LOCAL_IMAGE${NC}"
else
    echo -e "${RED}✗ Failed to build dev server image${NC}"
    exit 1
fi

# Push to registry if requested
if [ "$PUSH_TO_REGISTRY" = true ]; then
    echo ""
    echo -e "${YELLOW}→ Pushing to DigitalOcean Container Registry...${NC}"

    # Load DOCR_TOKEN from k8s/.env if it exists
    if [ -f "$PROJECT_ROOT/k8s/.env" ]; then
        source "$PROJECT_ROOT/k8s/.env"
    fi

    if [ -z "$DOCR_TOKEN" ]; then
        echo -e "${RED}✗ DOCR_TOKEN not found. Please set it in k8s/.env${NC}"
        echo -e "${YELLOW}  Get your token from: https://cloud.digitalocean.com/account/api/tokens${NC}"
        exit 1
    fi

    # Login to DigitalOcean Container Registry
    echo "$DOCR_TOKEN" | docker login registry.digitalocean.com -u "$DOCR_TOKEN" --password-stdin

    if [ $? -ne 0 ]; then
        echo -e "${RED}✗ Failed to login to DigitalOcean Container Registry${NC}"
        exit 1
    fi

    # Tag for remote registry
    docker tag "$LOCAL_IMAGE" "$REMOTE_IMAGE"

    # Push to registry
    docker push "$REMOTE_IMAGE"

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Image pushed successfully: $REMOTE_IMAGE${NC}"
    else
        echo -e "${RED}✗ Failed to push image to registry${NC}"
        exit 1
    fi
fi

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}Build Complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "Local image:  ${BLUE}$LOCAL_IMAGE${NC}"
if [ "$PUSH_TO_REGISTRY" = true ]; then
    echo -e "Remote image: ${BLUE}$REMOTE_IMAGE${NC}"
fi
echo ""
echo -e "${YELLOW}Next steps:${NC}"
if [ "$PUSH_TO_REGISTRY" = true ]; then
    echo -e "  • Image is ready for Kubernetes deployment"
    echo -e "  • Run: kubectl rollout restart deployment -n tesslate-user-environments"
else
    echo -e "  • Image is ready for local Docker development"
    echo -e "  • Run: docker compose up -d"
    echo -e "  • To push to registry: $0 --push"
fi
echo ""
