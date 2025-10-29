#!/bin/bash

# Create DigitalOcean Container Registry secret from environment variable
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

echo "Creating DigitalOcean Container Registry secret..."

# Create the secret in tesslate namespace
# Note: For DOCR, username can be any valid email format when using token auth
kubectl create secret docker-registry docr-secret \
    --docker-server=registry.digitalocean.com \
    --docker-username=token \
    --docker-password="$DOCR_TOKEN" \
    --namespace=tesslate \
    --dry-run=client -o yaml | kubectl apply -f -

echo "DOCR secret created in tesslate namespace!"

# Create the same secret in tesslate-user-environments namespace
kubectl create secret docker-registry docr-secret \
    --docker-server=registry.digitalocean.com \
    --docker-username=token \
    --docker-password="$DOCR_TOKEN" \
    --namespace=tesslate-user-environments \
    --dry-run=client -o yaml | kubectl apply -f -

echo "DOCR secret created in tesslate-user-environments namespace!"
echo "Registry authentication setup complete!"