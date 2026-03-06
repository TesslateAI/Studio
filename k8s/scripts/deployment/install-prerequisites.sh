#!/bin/bash

# Tesslate Studio - Install Kubernetes Prerequisites
# This script installs required cluster components before deploying the application

set -e

echo "================================================================"
echo "Tesslate Studio - Installing Kubernetes Prerequisites"
echo "================================================================"
echo ""

# Check if kubectl is configured
if ! kubectl cluster-info &>/dev/null; then
  echo "❌ ERROR: kubectl is not configured or cannot connect to cluster"
  exit 1
fi

echo "✅ kubectl configured and connected to cluster"
echo ""

# =============================================================================
# Install NGINX Ingress Controller
# =============================================================================

echo "🔍 Checking for NGINX Ingress Controller..."

if kubectl get namespace ingress-nginx &>/dev/null; then
  echo "✅ NGINX Ingress Controller namespace already exists"

  # Check if the controller deployment exists and is ready
  if kubectl get deployment ingress-nginx-controller -n ingress-nginx &>/dev/null; then
    echo "✅ NGINX Ingress Controller deployment found"
  else
    echo "⚠️  NGINX Ingress Controller namespace exists but deployment not found"
    echo "   Re-installing NGINX Ingress Controller..."
    kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.11.1/deploy/static/provider/cloud/deploy.yaml
  fi
else
  echo "⚠️  NGINX Ingress Controller not found. Installing..."
  kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.11.1/deploy/static/provider/cloud/deploy.yaml

  echo "⏳ Waiting for NGINX Ingress Controller to be ready..."
  kubectl wait --namespace ingress-nginx \
    --for=condition=ready pod \
    --selector=app.kubernetes.io/component=controller \
    --timeout=180s || {
      echo "❌ ERROR: NGINX Ingress Controller failed to become ready within timeout"
      echo "   Check pod status with: kubectl get pods -n ingress-nginx"
      exit 1
    }

  echo "✅ NGINX Ingress Controller installed successfully"
fi

# Wait for LoadBalancer to be assigned
echo "⏳ Waiting for LoadBalancer IP to be assigned..."
timeout=120
elapsed=0
while [ $elapsed -lt $timeout ]; do
  LB_IP=$(kubectl get svc ingress-nginx-controller -n ingress-nginx -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
  if [ -n "$LB_IP" ]; then
    echo "✅ LoadBalancer IP assigned: $LB_IP"
    break
  fi
  sleep 5
  elapsed=$((elapsed + 5))
done

if [ -z "$LB_IP" ]; then
  echo "⚠️  WARNING: LoadBalancer IP not assigned yet (this may take a few minutes)"
  echo "   You can check status with: kubectl get svc -n ingress-nginx ingress-nginx-controller"
fi

echo ""

# =============================================================================
# Install cert-manager
# =============================================================================

echo "🔍 Checking for cert-manager..."

if kubectl get namespace cert-manager &>/dev/null; then
  echo "✅ cert-manager namespace already exists"

  # Check if cert-manager deployment exists
  if kubectl get deployment cert-manager -n cert-manager &>/dev/null; then
    echo "✅ cert-manager deployment found"
  else
    echo "⚠️  cert-manager namespace exists but deployment not found"
    echo "   Re-installing cert-manager..."
    kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.15.0/cert-manager.yaml
  fi
else
  echo "⚠️  cert-manager not found. Installing..."
  kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.15.0/cert-manager.yaml

  echo "⏳ Waiting for cert-manager to be ready..."

  # Wait for cert-manager webhook to be ready
  kubectl wait --namespace cert-manager \
    --for=condition=ready pod \
    --selector=app.kubernetes.io/name=cert-manager \
    --timeout=180s || {
      echo "❌ ERROR: cert-manager failed to become ready within timeout"
      echo "   Check pod status with: kubectl get pods -n cert-manager"
      exit 1
    }

  # Give cert-manager a few extra seconds to fully initialize webhooks
  echo "⏳ Waiting for cert-manager webhooks to initialize..."
  sleep 10

  echo "✅ cert-manager installed successfully"
fi

echo ""

# =============================================================================
# Configure NGINX Ingress Controller for snippet annotations
# =============================================================================

echo "🔍 Configuring NGINX Ingress Controller to allow snippet annotations..."

# Apply the ConfigMap to enable snippets (required for user authentication)
MANIFEST_DIR="$(cd "$(dirname "$0")/../../manifests/ingress" && pwd)"
kubectl apply -f "$MANIFEST_DIR/nginx-enable-snippets.yaml"

# Check if the controller needs to be restarted
CURRENT_CONFIG=$(kubectl get configmap ingress-nginx-controller -n ingress-nginx -o jsonpath='{.data.allow-snippet-annotations}' 2>/dev/null || echo "")

if [ "$CURRENT_CONFIG" != "true" ]; then
  echo "⏳ Restarting NGINX Ingress Controller to apply configuration..."
  kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
  kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=120s
  echo "✅ NGINX Ingress Controller configuration updated"
else
  echo "✅ Snippet annotations already enabled"
fi

echo ""

# =============================================================================
# Verify installations
# =============================================================================

echo "🔍 Verifying prerequisites installation..."
echo ""

echo "NGINX Ingress Controller:"
kubectl get pods -n ingress-nginx -l app.kubernetes.io/component=controller

echo ""
echo "cert-manager:"
kubectl get pods -n cert-manager -l app.kubernetes.io/name=cert-manager

echo ""

# Check if LoadBalancer IP is assigned
LB_IP=$(kubectl get svc ingress-nginx-controller -n ingress-nginx -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
if [ -n "$LB_IP" ]; then
  echo "📍 LoadBalancer IP: $LB_IP"
  echo ""
  echo "⚠️  IMPORTANT: Update your DNS records to point to this IP:"
  echo "   studio-test.tesslate.com → $LB_IP"
  echo "   *.studio-test.tesslate.com → $LB_IP"
else
  echo "⚠️  LoadBalancer IP not yet assigned"
  echo "   Run this command to check when it's ready:"
  echo "   kubectl get svc -n ingress-nginx ingress-nginx-controller"
fi

echo ""
echo "================================================================"
echo "✅ All prerequisites installed successfully!"
echo "================================================================"
echo ""
echo "Next steps:"
echo "  1. Run: ./k8s/scripts/deployment/setup-registry-auth.sh"
echo "  2. Run: ./k8s/scripts/deployment/build-push-images.sh"
echo "  3. Configure secrets in k8s/manifests/security/"
echo "  4. Run: ./k8s/scripts/deployment/deploy-application.sh"
echo ""
echo "Or run the complete deployment:"
echo "  ./k8s/scripts/deployment/deploy-all.sh"
echo ""
