#!/bin/bash

# Build and push images to DigitalOcean Container Registry
set -e

# Change to scripts directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Load environment variables from k8s/.env if it exists
ENV_FILE="$SCRIPT_DIR/../../.env"
if [ -f "$ENV_FILE" ]; then
    echo "Loading environment variables from k8s/.env"
    set -a
    source "$ENV_FILE"
    set +a
fi

REGISTRY="registry.digitalocean.com/finetune"
BACKEND_IMAGE="${REGISTRY}/tesslate-backend:latest"
FRONTEND_IMAGE="${REGISTRY}/tesslate-frontend:latest"
DEV_SERVER_IMAGE="${REGISTRY}/tesslate-dev-server:latest"

echo "Building and pushing Tesslate images to DigitalOcean Container Registry..."

# Navigate to project root
cd "$SCRIPT_DIR/../../.."

# Login to DigitalOcean Container Registry
echo "Logging in to DigitalOcean Container Registry..."
if [ -z "$DOCR_TOKEN" ]; then
    echo "Error: DOCR_TOKEN environment variable is not set"
    echo ""
    echo "Please either:"
    echo "  1. Create k8s/.env file with DOCR_TOKEN (recommended):"
    echo "     cd k8s && cp .env.example .env"
    echo "     Then edit .env and add your token"
    echo ""
    echo "  2. Or set it manually:"
    echo "     export DOCR_TOKEN=your_token_here"
    echo ""
    echo "Get your token from: https://cloud.digitalocean.com/account/api/tokens"
    exit 1
fi
echo "$DOCR_TOKEN" | docker login registry.digitalocean.com -u token --password-stdin

# Build backend image
echo "Building backend image..."
docker build -t "${BACKEND_IMAGE}" -f orchestrator/Dockerfile orchestrator/

# Build frontend image (production version with nginx)
echo "Building frontend image..."
docker build -t "${FRONTEND_IMAGE}" -f app/Dockerfile.prod app/

# Build dev server image (for user development environments)
echo "Building dev server image..."
docker build -t "${DEV_SERVER_IMAGE}" -f orchestrator/Dockerfile.devserver orchestrator/

# Push images to registry
echo "Pushing backend image to DOCR..."
docker push "${BACKEND_IMAGE}"

echo "Pushing frontend image to DOCR..."
docker push "${FRONTEND_IMAGE}"

echo "Pushing dev server image to DOCR..."
docker push "${DEV_SERVER_IMAGE}"

echo "Successfully built and pushed images to DigitalOcean Container Registry!"
echo "Backend: ${BACKEND_IMAGE}"
echo "Frontend: ${FRONTEND_IMAGE}"
echo "Dev Server: ${DEV_SERVER_IMAGE}"