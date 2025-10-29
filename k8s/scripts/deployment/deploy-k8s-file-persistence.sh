#!/bin/bash
set -e

# Deploy K8s File Persistence Implementation
# This script deploys the stateless backend with K8s API-based file operations

echo "=========================================="
echo "K8s File Persistence Deployment"
echo "=========================================="

# Check prerequisites
if [ -z "$DOCR_TOKEN" ]; then
    echo "❌ Error: DOCR_TOKEN environment variable not set"
    echo "Usage: DOCR_TOKEN=your_token ./deploy-k8s-file-persistence.sh"
    exit 1
fi

if ! command -v kubectl &> /dev/null; then
    echo "❌ Error: kubectl not found"
    exit 1
fi

if ! command -v docker &> /dev/null; then
    echo "❌ Error: docker not found"
    exit 1
fi

# Set working directory
cd "$(dirname "$0")/../../.."
REPO_ROOT=$(pwd)

echo "Repository root: $REPO_ROOT"
echo ""

# Step 1: Build backend image
echo "=========================================="
echo "Step 1: Building Backend Image"
echo "=========================================="

cd "$REPO_ROOT/orchestrator"

echo "Building tesslate-backend:latest..."
docker build -t registry.digitalocean.com/finetune/tesslate-backend:latest .

if [ $? -ne 0 ]; then
    echo "❌ Docker build failed"
    exit 1
fi

echo "✅ Backend image built successfully"
echo ""

# Step 2: Push to registry
echo "=========================================="
echo "Step 2: Pushing to Container Registry"
echo "=========================================="

echo "Logging in to registry..."
echo "$DOCR_TOKEN" | docker login registry.digitalocean.com -u "$DOCR_TOKEN" --password-stdin

if [ $? -ne 0 ]; then
    echo "❌ Docker login failed"
    exit 1
fi

echo "Pushing image..."
docker push registry.digitalocean.com/finetune/tesslate-backend:latest

if [ $? -ne 0 ]; then
    echo "❌ Docker push failed"
    exit 1
fi

echo "✅ Image pushed successfully"
echo ""

# Step 3: Apply RBAC configuration
echo "=========================================="
echo "Step 3: Applying RBAC Configuration"
echo "=========================================="

cd "$REPO_ROOT"

echo "Creating RBAC resources..."
kubectl apply -f k8s/manifests/rbac/backend-role.yaml
kubectl apply -f k8s/manifests/rbac/backend-rolebinding.yaml

if [ $? -ne 0 ]; then
    echo "⚠️  Warning: RBAC apply had issues (may already exist)"
else
    echo "✅ RBAC configured successfully"
fi

echo ""

# Step 4: Restart backend deployment
echo "=========================================="
echo "Step 4: Restarting Backend Deployment"
echo "=========================================="

echo "Restarting tesslate-backend..."
kubectl rollout restart deployment/tesslate-backend -n tesslate

if [ $? -ne 0 ]; then
    echo "❌ Deployment restart failed"
    exit 1
fi

echo "Waiting for rollout to complete..."
kubectl rollout status deployment/tesslate-backend -n tesslate --timeout=5m

if [ $? -ne 0 ]; then
    echo "❌ Rollout failed or timed out"
    echo "Check logs: kubectl logs -f deployment/tesslate-backend -n tesslate"
    exit 1
fi

echo "✅ Backend restarted successfully"
echo ""

# Step 5: Verify deployment
echo "=========================================="
echo "Step 5: Verifying Deployment"
echo "=========================================="

echo "Checking backend pods..."
kubectl get pods -n tesslate -l app=tesslate-backend

echo ""
echo "Checking recent logs..."
kubectl logs -n tesslate deployment/tesslate-backend --tail=20 | grep -E "\[K8S\]|Kubernetes client initialized" || true

echo ""
echo "=========================================="
echo "✅ Deployment Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Monitor logs: kubectl logs -f deployment/tesslate-backend -n tesslate"
echo "2. Test file operations (see K8S_FILE_PERSISTENCE_IMPLEMENTATION.md)"
echo "3. Check for errors: kubectl logs deployment/tesslate-backend -n tesslate | grep ERROR"
echo ""
echo "Rollback if needed: kubectl rollout undo deployment/tesslate-backend -n tesslate"
echo ""
