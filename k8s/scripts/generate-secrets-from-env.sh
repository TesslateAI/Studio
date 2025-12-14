#!/bin/bash
# Generate Kubernetes Secrets from .env file
# Usage: ./generate-secrets-from-env.sh [minikube|production]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="$(dirname "$SCRIPT_DIR")"

# Default to minikube
ENVIRONMENT="${1:-minikube}"

ENV_FILE="$K8S_DIR/.env.$ENVIRONMENT"

if [ ! -f "$ENV_FILE" ]; then
    echo "❌ Error: $ENV_FILE not found"
    echo ""
    echo "Usage: $0 [minikube|production]"
    echo ""
    echo "Create your env file:"
    echo "  cp $K8S_DIR/.env.example $ENV_FILE"
    echo "  # Then edit $ENV_FILE with your values"
    exit 1
fi

echo "🔐 Generating Kubernetes Secrets from $ENV_FILE"
echo "================================================="
echo ""

# Load environment variables
set -a
source "$ENV_FILE"
set +a

# Determine output directory based on environment
if [ "$ENVIRONMENT" = "minikube" ]; then
    OUTPUT_DIR="$K8S_DIR/overlays/minikube/secrets"
    NAMESPACE="tesslate"
    DB_HOST="postgres"
else
    OUTPUT_DIR="$K8S_DIR/manifests/security"
    NAMESPACE="tesslate"
    DB_HOST="postgres.tesslate.svc.cluster.local"
fi

mkdir -p "$OUTPUT_DIR"

echo "📋 Configuration:"
echo "   Environment: $ENVIRONMENT"
echo "   Domain: $APP_DOMAIN"
echo "   Output: $OUTPUT_DIR"
echo ""

# Build DATABASE_URL
DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${DB_HOST}:5432/${POSTGRES_DB}"

# Generate postgres-secret.yaml
echo "📝 Creating postgres-secret.yaml..."
cat > "$OUTPUT_DIR/postgres-secret.yaml" << EOF
# PostgreSQL Credentials for ${ENVIRONMENT^}
# Generated from k8s/.env.$ENVIRONMENT

apiVersion: v1
kind: Secret
metadata:
  name: postgres-secret
  namespace: $NAMESPACE
type: Opaque
stringData:
  POSTGRES_DB: "$POSTGRES_DB"
  POSTGRES_USER: "$POSTGRES_USER"
  POSTGRES_PASSWORD: "$POSTGRES_PASSWORD"
EOF
echo "✅ postgres-secret.yaml created"

# Generate s3-credentials.yaml
echo "📝 Creating s3-credentials.yaml..."
cat > "$OUTPUT_DIR/s3-credentials.yaml" << EOF
# S3 Credentials for ${ENVIRONMENT^}
# Generated from k8s/.env.$ENVIRONMENT

apiVersion: v1
kind: Secret
metadata:
  name: s3-credentials
  namespace: $NAMESPACE
type: Opaque
stringData:
  S3_ACCESS_KEY_ID: "$S3_ACCESS_KEY_ID"
  S3_SECRET_ACCESS_KEY: "$S3_SECRET_ACCESS_KEY"
  S3_BUCKET_NAME: "$S3_BUCKET_NAME"
  S3_ENDPOINT_URL: "$S3_ENDPOINT_URL"
  S3_REGION: "$S3_REGION"
EOF
echo "✅ s3-credentials.yaml created"

# Generate app-secrets.yaml
echo "📝 Creating app-secrets.yaml..."
cat > "$OUTPUT_DIR/app-secrets.yaml" << EOF
# Application Secrets for ${ENVIRONMENT^}
# Generated from k8s/.env.$ENVIRONMENT

apiVersion: v1
kind: Secret
metadata:
  name: tesslate-app-secrets
  namespace: $NAMESPACE
type: Opaque
stringData:
  # Core settings
  SECRET_KEY: "$SECRET_KEY"
  DATABASE_URL: "$DATABASE_URL"

  # LiteLLM Configuration
  LITELLM_API_BASE: "$LITELLM_API_BASE"
  LITELLM_MASTER_KEY: "$LITELLM_MASTER_KEY"
  LITELLM_DEFAULT_MODELS: "$LITELLM_DEFAULT_MODELS"
  LITELLM_TEAM_ID: "$LITELLM_TEAM_ID"
  LITELLM_EMAIL_DOMAIN: "$LITELLM_EMAIL_DOMAIN"
  LITELLM_INITIAL_BUDGET: "$LITELLM_INITIAL_BUDGET"

  # Domain settings
  APP_DOMAIN: "$APP_DOMAIN"
  APP_BASE_URL: "${APP_PROTOCOL}://${APP_DOMAIN}"
  DEV_SERVER_BASE_URL: "${APP_PROTOCOL}://${APP_DOMAIN}"
  CORS_ORIGINS: "${APP_PROTOCOL}://${APP_DOMAIN}"
  ALLOWED_HOSTS: "$APP_DOMAIN"

  # Cookie settings
  COOKIE_SECURE: "$COOKIE_SECURE"
  COOKIE_SAMESITE: "$COOKIE_SAMESITE"
  COOKIE_DOMAIN: "$COOKIE_DOMAIN"

  # Deployment mode
  DEPLOYMENT_MODE: "kubernetes"

  # OAuth Configuration
  GOOGLE_CLIENT_ID: "$GOOGLE_CLIENT_ID"
  GOOGLE_CLIENT_SECRET: "$GOOGLE_CLIENT_SECRET"
  GOOGLE_OAUTH_REDIRECT_URI: "$GOOGLE_OAUTH_REDIRECT_URI"
  GITHUB_CLIENT_ID: "$GITHUB_CLIENT_ID"
  GITHUB_CLIENT_SECRET: "$GITHUB_CLIENT_SECRET"
  GITHUB_OAUTH_REDIRECT_URI: "$GITHUB_OAUTH_REDIRECT_URI"

  # Stripe Configuration
  STRIPE_SECRET_KEY: "$STRIPE_SECRET_KEY"
  STRIPE_PUBLISHABLE_KEY: "$STRIPE_PUBLISHABLE_KEY"
  STRIPE_WEBHOOK_SECRET: "$STRIPE_WEBHOOK_SECRET"
  STRIPE_PREMIUM_PRICE_ID: "$STRIPE_PREMIUM_PRICE_ID"
  PREMIUM_SUBSCRIPTION_PRICE: "$PREMIUM_SUBSCRIPTION_PRICE"
  CREDIT_PACKAGE_SMALL: "$CREDIT_PACKAGE_SMALL"
  CREDIT_PACKAGE_MEDIUM: "$CREDIT_PACKAGE_MEDIUM"
  CREDIT_PACKAGE_LARGE: "$CREDIT_PACKAGE_LARGE"
  FREE_MAX_PROJECTS: "$FREE_MAX_PROJECTS"
  PREMIUM_MAX_PROJECTS: "$PREMIUM_MAX_PROJECTS"

  # PostHog Analytics
  VITE_PUBLIC_POSTHOG_KEY: "$VITE_PUBLIC_POSTHOG_KEY"
  VITE_PUBLIC_POSTHOG_HOST: "$VITE_PUBLIC_POSTHOG_HOST"
EOF
echo "✅ app-secrets.yaml created"

echo ""
echo "✅ All secrets generated successfully!"
echo ""
echo "📋 Files created in $OUTPUT_DIR:"
echo "   - postgres-secret.yaml"
echo "   - s3-credentials.yaml"
echo "   - app-secrets.yaml"
echo ""
echo "🔒 Security Notes:"
echo "   ✅ These files are gitignored (do NOT commit to git)"
echo "   ✅ Credentials sourced from k8s/.env.$ENVIRONMENT"
echo ""

if [ "$ENVIRONMENT" = "minikube" ]; then
    echo "📋 Next Steps for Minikube:"
    echo "   1. Apply secrets to cluster:"
    echo "      kubectl apply -k $K8S_DIR/overlays/minikube"
    echo ""
    echo "   2. Or apply secrets only:"
    echo "      kubectl apply -f $OUTPUT_DIR/"
else
    echo "📋 Next Steps for Production:"
    echo "   1. Apply secrets to cluster:"
    echo "      kubectl apply -f $OUTPUT_DIR/"
    echo ""
    echo "   2. Deploy application:"
    echo "      cd $K8S_DIR/scripts/deployment && ./deploy-all.sh"
fi
echo ""
