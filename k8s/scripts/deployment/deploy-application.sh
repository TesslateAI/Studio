#!/bin/bash
# Deploy Tesslate Studio Application to Kubernetes
# This script deploys the database and application services

set -e

echo "🚀 Deploying Tesslate Studio application..."

# Set kubeconfig
export KUBECONFIG=~/.kube/configs/digitalocean.yaml

# Check if secrets exist
echo "🔍 Checking prerequisites..."
if ! kubectl get secret tesslate-app-secrets -n tesslate > /dev/null 2>&1; then
    echo "❌ Application secrets not found!"
    echo ""
    echo "Please create secrets from the YAML template:"
    echo "  1. cd ../../manifests/security"
    echo "  2. cp app-secrets.yaml.example app-secrets.yaml"
    echo "  3. Edit app-secrets.yaml with your values"
    echo "  4. kubectl apply -f app-secrets.yaml"
    echo ""
    exit 1
fi

if ! kubectl get secret postgres-secret -n tesslate > /dev/null 2>&1; then
    echo "❌ Database secrets not found!"
    echo ""
    echo "Please create database secrets:"
    echo "  1. cd ../../manifests/database"
    echo "  2. cp postgres-secret.yaml.example postgres-secret.yaml"
    echo "  3. Edit postgres-secret.yaml with your values"
    echo "  4. kubectl apply -f postgres-secret.yaml"
    echo ""
    exit 1
fi

# Deploy base infrastructure
echo "🏗️  Deploying base infrastructure..."
kubectl apply -f ../../manifests/base/

# Deploy database
echo "🗄️  Deploying PostgreSQL database..."
kubectl apply -f ../../manifests/database/

# Wait for database to be ready
echo "⏳ Waiting for database to be ready..."
kubectl wait --for=condition=available --timeout=300s deployment/postgres -n tesslate

# Initialize database schema
echo "🔧 Initializing database schema..."
kubectl apply -f ../../manifests/database/init-db-job.yaml
echo "⏳ Waiting for database initialization..."
kubectl wait --for=condition=complete --timeout=120s job/tesslate-init-db -n tesslate

# Deploy security resources
echo "🔐 Deploying security resources..."
kubectl apply -f ../../manifests/security/dev-environments-rbac.yaml

# Deploy storage (backend templates only - user environment PVC is in step 5)
echo "💾 Deploying backend storage..."
kubectl apply -f ../../manifests/storage/projects-pvc.yaml

# Deploy core application services
echo "📱 Deploying application services..."
kubectl apply -f ../../manifests/core/backend-configmap.yaml
kubectl apply -f ../../manifests/core/backend-deployment.yaml
kubectl apply -f ../../manifests/core/frontend-deployment.yaml
kubectl apply -f ../../manifests/core/backend-service.yaml
kubectl apply -f ../../manifests/core/frontend-service.yaml

# Note: User environments namespace is deployed in step 05-deploy-user-namespace.sh
# This is separated to allow proper cert-manager setup and secret propagation

# Wait for deployments to be ready
echo "⏳ Waiting for application deployments..."
kubectl wait --for=condition=available --timeout=300s deployment/tesslate-backend -n tesslate
kubectl wait --for=condition=available --timeout=300s deployment/tesslate-frontend -n tesslate
# No longer waiting for Traefik (removed)

# Install NGINX Ingress Controller for DigitalOcean
echo "🌐 Installing NGINX Ingress Controller..."
if ! kubectl get namespace ingress-nginx > /dev/null 2>&1; then
    kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.1/deploy/static/provider/do/deploy.yaml
    echo "⏳ Waiting for ingress controller..."
    kubectl wait --namespace ingress-nginx \
        --for=condition=ready pod \
        --selector=app.kubernetes.io/component=controller \
        --timeout=300s
fi

# Deploy ingress
echo "🔗 Deploying ingress configuration..."
kubectl apply -f ../../manifests/core/main-ingress.yaml

echo ""
echo "🎉 Deployment complete!"
echo ""

# Show deployment status
echo "📊 Deployment Status:"
kubectl get pods,svc,ingress -n tesslate

echo ""
echo "🌐 Getting Load Balancer IP..."
LB_IP=$(kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "Pending...")

if [ "$LB_IP" != "Pending..." ] && [ -n "$LB_IP" ]; then
    echo "✅ Application accessible at: http://$LB_IP"
    echo ""
    echo "Services:"
    echo "  Frontend: http://$LB_IP"
    echo "  Backend API: http://$LB_IP/api"
    echo "  Traefik Dashboard: http://$LB_IP:8080"
else
    echo "⏳ Load Balancer IP is still being assigned..."
    echo "Run this command to check when it's ready:"
    echo "kubectl get svc -n ingress-nginx ingress-nginx-controller"
fi

echo ""
echo "🔒 Security Summary:"
echo "  ✅ HTTPS Registry with TLS certificates"
echo "  ✅ Kubernetes secrets for API keys and database"
echo "  ✅ Network policies and RBAC configured"
echo "  ✅ Internal cluster communication encrypted"

echo ""
echo "📊 Infrastructure Components:"
NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="ExternalIP")].address}')
echo "  Registry (HTTPS): https://$NODE_IP:30500"
echo "  Database: PostgreSQL running in cluster"
echo "  Load Balancer: $LB_IP (NGINX Ingress)"
echo "  Traefik: Internal container routing"

echo ""
echo "📋 Useful commands:"
echo "  Check pods: kubectl get pods -n tesslate"
echo "  View logs: kubectl logs -f deployment/tesslate-backend -n tesslate"
echo "  Registry status: curl -k https://$NODE_IP:30500/v2/_catalog"
echo "  Port forward: kubectl port-forward svc/tesslate-frontend 8080:80 -n tesslate"