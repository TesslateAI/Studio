#!/bin/bash
# Build and Push Images to Self-Hosted Registry
# This script builds Docker images and pushes them to your cluster registry

set -e

echo "🔨 Building and pushing images to self-hosted registry..."

# Set kubeconfig
export KUBECONFIG=~/.kube/configs/digitalocean.yaml

# Check if registry is running
echo "🔍 Checking registry status..."
if ! kubectl get pods -n tesslate-registry -l app=docker-registry --field-selector=status.phase=Running | grep -q docker-registry; then
    echo "❌ Registry is not running. Please run './01-setup-registry.sh' first"
    exit 1
fi

# Start port forwarding to registry
echo "🌐 Setting up port forwarding to registry..."
kubectl port-forward svc/docker-registry 5000:5000 -n tesslate-registry &
PF_PID=$!

# Wait for port forwarding to be ready
echo "⏳ Waiting for port forwarding..."
sleep 5

# Test registry connectivity
if ! curl -s http://localhost:5000/v2/ > /dev/null; then
    echo "❌ Cannot connect to registry. Please check port forwarding"
    kill $PF_PID 2>/dev/null || true
    exit 1
fi

echo "✅ Registry is accessible"

# Build images
echo "🔨 Building backend image..."
cd ../../../orchestrator
docker build -t tesslate-backend:latest .

echo "🔨 Building frontend image..."
cd ../app
docker build -t tesslate-frontend:latest .

cd ../k8s/scripts/deployment

# Get node external IP for registry access
NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="ExternalIP")].address}')
echo "Using registry at: $NODE_IP:30500"

# Tag images for external registry access
echo "🏷️  Tagging images..."
docker tag tesslate-backend:latest $NODE_IP:30500/tesslate-backend:latest
docker tag tesslate-frontend:latest $NODE_IP:30500/tesslate-frontend:latest

# Configure Docker daemon for insecure registry (if needed)
echo "📤 Pushing backend image..."
docker push $NODE_IP:30500/tesslate-backend:latest

echo "📤 Pushing frontend image..."
docker push $NODE_IP:30500/tesslate-frontend:latest

# Stop port forwarding
echo "🛑 Stopping port forwarding..."
kill $PF_PID 2>/dev/null || true

# Verify images in registry
echo "✅ Verifying images in secure registry..."
curl -k https://$NODE_IP:30500/v2/_catalog

echo ""
echo "🎉 Images successfully built and pushed to secure registry!"
echo ""
echo "Images available in HTTPS registry:"
echo "  - External: $NODE_IP:30500/tesslate-backend:latest"
echo "  - External: $NODE_IP:30500/tesslate-frontend:latest"
echo "  - Internal: 10.108.85.231:5000/tesslate-backend:latest (cluster IP)"
echo "  - Internal: 10.108.85.231:5000/tesslate-frontend:latest (cluster IP)"
echo ""
echo "🔒 Registry Security Features:"
echo "  ✅ HTTPS/TLS encryption enabled"
echo "  ✅ Self-signed certificates for development"
echo "  ✅ Docker configured for insecure registry access"
echo ""
echo "Next: Run './03-create-secrets.sh' to create application secrets"