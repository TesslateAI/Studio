#!/bin/bash

# Tesslate Studio - Deploy Application to Kubernetes

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFESTS_DIR="$(dirname "$SCRIPT_DIR")/manifests"

echo "========================================"
echo "Tesslate Studio Deployment"
echo "========================================"

# Check if kubectl is configured
if ! kubectl cluster-info &> /dev/null; then
    echo "Error: kubectl is not configured or cluster is not accessible"
    exit 1
fi

# Deploy base infrastructure
echo "[1/6] Deploying base infrastructure..."
kubectl apply -f $MANIFESTS_DIR/base/

# Wait for namespaces
sleep 5

# Deploy local registry
echo "[2/6] Deploying local container registry..."
kubectl apply -f $MANIFESTS_DIR/registry/

# Deploy PostgreSQL database
echo "[3/6] Deploying PostgreSQL database..."
kubectl apply -f $MANIFESTS_DIR/database/

# Wait for database to be ready
echo "Waiting for PostgreSQL to be ready..."
kubectl wait --for=condition=ready pod -l app=postgres -n tesslate --timeout=300s

# Deploy application (backend and frontend)
echo "[4/6] Deploying Tesslate application..."
kubectl apply -f $MANIFESTS_DIR/app/

# Wait for deployments to be ready
echo "[5/6] Waiting for application to be ready..."
kubectl wait --for=condition=available deployment/tesslate-backend -n tesslate --timeout=300s
kubectl wait --for=condition=available deployment/tesslate-frontend -n tesslate --timeout=300s

# Show deployment status
echo "[6/6] Deployment Status:"
echo ""
echo "Namespaces:"
kubectl get namespaces | grep tesslate

echo ""
echo "Pods:"
kubectl get pods -n tesslate

echo ""
echo "Services:"
kubectl get services -n tesslate

echo ""
echo "Ingress:"
kubectl get ingress -n tesslate

echo ""
echo "Registry:"
kubectl get pods -n tesslate-registry

echo ""
echo "========================================"
echo "Deployment Complete!"
echo "========================================"
echo ""
echo "Access the application at:"
echo "  http://<SERVER_IP>:30080"
echo "  or configure /etc/hosts with: <SERVER_IP> tesslate.local"
echo "  then access: http://tesslate.local:30080"
echo ""
echo "Local Docker Registry available at:"
echo "  <SERVER_IP>:30500"
echo ""
echo "To check logs:"
echo "  kubectl logs -f deployment/tesslate-backend -n tesslate"
echo "  kubectl logs -f deployment/tesslate-frontend -n tesslate"
echo "========================================"