#!/bin/bash
# Deploy Tesslate Studio Application to Kubernetes
# This script deploys the database and application services

set -e

echo "🚀 Deploying Tesslate Studio application..."

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

# Validate database password consistency
echo "🔍 Validating database credentials..."
PG_PASSWORD=$(kubectl get secret postgres-secret -n tesslate -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d)
DATABASE_URL=$(kubectl get secret tesslate-app-secrets -n tesslate -o jsonpath='{.data.DATABASE_URL}' | base64 -d)

# Extract password from DATABASE_URL (format: postgresql+asyncpg://user:password@host:port/db)
# Use grep with Perl regex to extract the password between : and @
DB_URL_PASSWORD=$(echo "$DATABASE_URL" | grep -oP '://[^:]+:\K[^@]+')

if [ "$PG_PASSWORD" != "$DB_URL_PASSWORD" ]; then
    echo "❌ ERROR: Password mismatch detected!"
    echo ""
    echo "The password in postgres-secret (POSTGRES_PASSWORD) does not match"
    echo "the password in app-secrets (DATABASE_URL)."
    echo ""
    echo "PostgreSQL expects: $PG_PASSWORD"
    echo "Backend will use:    $DB_URL_PASSWORD"
    echo ""
    echo "Please ensure both secrets use the same password:"
    echo "  1. Edit k8s/manifests/database/postgres-secret.yaml"
    echo "  2. Edit k8s/manifests/security/app-secrets.yaml"
    echo "  3. Update both to use the same password"
    echo "  4. Apply both secrets:"
    echo "     kubectl apply -f k8s/manifests/database/postgres-secret.yaml"
    echo "     kubectl apply -f k8s/manifests/security/app-secrets.yaml"
    echo ""
    exit 1
fi

echo "✅ Database credentials validated successfully"

# Deploy base infrastructure
echo "🏗️  Deploying base infrastructure..."
kubectl apply -f ../../manifests/base/

# Deploy database
echo "🗄️  Deploying PostgreSQL database..."
kubectl apply -f ../../manifests/database/

# Wait for database to be ready
echo "⏳ Waiting for database to be ready..."
kubectl wait --for=condition=available --timeout=300s deployment/postgres -n tesslate

# Database schema will be initialized automatically by SQLAlchemy on first backend startup
echo "✅ Database ready (schema will be created automatically by backend)"

# Deploy security resources
echo "🔐 Deploying security resources..."
kubectl apply -f ../../manifests/security/dev-environments-rbac.yaml

# Deploy storage (backend templates only - user environment PVC is in step 5)
echo "💾 Deploying backend storage..."
# Note: User environment PVC will be deployed in deploy-user-namespace.sh

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
else
    echo "⏳ Load Balancer IP is still being assigned..."
    echo "Run this command to check when it's ready:"
    echo "kubectl get svc -n ingress-nginx ingress-nginx-controller"
fi

echo ""
echo "🔒 Security Summary:"
echo "  ✅ Kubernetes secrets for API keys and database"
echo "  ✅ RBAC and network policies configured"
echo "  ✅ Internal cluster communication encrypted"
echo "  ✅ NGINX Ingress Controller with SSL support"

echo ""
echo "📊 Infrastructure Components:"
echo "  Database: PostgreSQL running in cluster"
echo "  Load Balancer: $LB_IP (NGINX Ingress)"
echo "  Container Registry: DigitalOcean Container Registry"

echo ""
echo "📋 Useful commands:"
echo "  Check pods: kubectl get pods -n tesslate"
echo "  View logs: kubectl logs -f deployment/tesslate-backend -n tesslate"
echo "  View ingress: kubectl get ingress -n tesslate"
echo "  Port forward: kubectl port-forward svc/tesslate-frontend 8080:80 -n tesslate"