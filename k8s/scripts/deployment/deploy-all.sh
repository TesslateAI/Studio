#!/bin/bash
# Complete OpenSail Deployment Script
# This script runs all deployment steps in sequence

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

# Check prerequisites
if [ -z "$DOCR_TOKEN" ]; then
    echo "❌ Error: DOCR_TOKEN environment variable is not set"
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

echo "🚀 Starting complete OpenSail deployment..."
echo "This will:"
echo "  0. Install Kubernetes prerequisites (NGINX Ingress, cert-manager)"
echo "  1. Setup DigitalOcean Container Registry authentication"
echo "  2. Build and push application images to registry"
echo "  3. Setup application secrets (API keys, database, etc.)"
echo "  4. Deploy the full application to Kubernetes"
echo ""

# Confirm before proceeding
read -p "Continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Deployment cancelled"
    exit 1
fi

# Step 0: Install prerequisites
echo ""
echo "==============================================="
echo "STEP 0: Installing Kubernetes prerequisites"
echo "==============================================="
./install-prerequisites.sh

# Step 1: Setup registry authentication
echo ""
echo "==============================================="
echo "STEP 1: Setting up registry authentication"
echo "==============================================="
./setup-registry-auth.sh

# Step 2: Build and push images
echo ""
echo "==============================================="
echo "STEP 2: Building and pushing images"
echo "==============================================="
./build-push-images.sh

# Step 3: Check application secrets
echo ""
echo "==============================================="
echo "STEP 3: Checking application secrets"
echo "==============================================="

# Check if secrets exist
if kubectl get secret tesslate-app-secrets -n tesslate &>/dev/null && \
   kubectl get secret postgres-secret -n tesslate &>/dev/null; then
    echo "✅ Application secrets found"
else
    echo "❌ Application secrets not found!"
    echo ""
    echo "Please create secrets from the YAML template:"
    echo "  1. cd ../../manifests/security"
    echo "  2. cp app-secrets.yaml.example app-secrets.yaml"
    echo "  3. Edit app-secrets.yaml with your values"
    echo "  4. kubectl apply -f app-secrets.yaml"
    echo "  5. kubectl apply -f postgres-secret.yaml (if using PostgreSQL)"
    echo ""
    exit 1
fi

# Step 4: Deploy application
echo ""
echo "==============================================="
echo "STEP 4: Deploying application"
echo "==============================================="
./deploy-application.sh

# Step 5: Deploy user environments namespace
echo ""
echo "==============================================="
echo "STEP 5: Setting up user environments namespace"
echo "==============================================="
./deploy-user-namespace.sh

echo ""
echo "🎉 Complete deployment finished!"
echo ""
echo "OpenSail is now running on Kubernetes!"
echo ""
echo "📋 What was deployed:"
echo "  ✅ Kubernetes prerequisites (NGINX Ingress Controller, cert-manager)"
echo "  ✅ DigitalOcean Container Registry authentication"
echo "  ✅ Application images (backend, frontend, dev-server)"
echo "  ✅ PostgreSQL database"
echo "  ✅ Main application (tesslate namespace)"
echo "  ✅ User environments infrastructure (tesslate-user-environments namespace)"
echo "  ✅ Ingress with SSL certificates"
echo "  ✅ RBAC and security policies"
echo ""
echo "Check the output above for access URLs and next steps."