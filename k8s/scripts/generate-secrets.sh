#!/bin/bash
# Generate Kubernetes Secrets for Tesslate Studio
# This script creates all necessary secret files with strong random passwords

set -e

echo "🔐 Generating Kubernetes Secrets for Tesslate Studio"
echo "===================================================="
echo ""

# Prompt for domain
echo "What domain will you use for your application?"
echo "Example: studio.tesslate.com"
read -p "Domain: " APP_DOMAIN

if [ -z "$APP_DOMAIN" ]; then
    echo "❌ Error: Domain is required"
    exit 1
fi

echo ""
echo "What email should we use for Let's Encrypt SSL certificate notifications?"
read -p "Email: " SSL_EMAIL

if [ -z "$SSL_EMAIL" ]; then
    echo "❌ Error: Email is required"
    exit 1
fi

echo ""
echo "📋 Configuration:"
echo "   Domain: $APP_DOMAIN"
echo "   Email: $SSL_EMAIL"
echo ""
read -p "Continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled"
    exit 1
fi

echo ""
echo "🔑 Generating secure passwords..."

# Generate passwords
POSTGRES_PASSWORD=$(openssl rand -base64 32)
SECRET_KEY=$(openssl rand -base64 64)
CSRF_SECRET=$(openssl rand -base64 32)

echo "✅ Passwords generated!"
echo ""

# Create manifests/security directory if it doesn't exist
mkdir -p manifests/security

echo "📝 Creating postgres-secret.yaml..."
cat > manifests/security/postgres-secret.yaml << EOF
apiVersion: v1
kind: Secret
metadata:
  name: postgres-secret
  namespace: tesslate
type: Opaque
stringData:
  POSTGRES_DB: tesslate
  POSTGRES_USER: tesslate_user
  POSTGRES_PASSWORD: $POSTGRES_PASSWORD
EOF

echo "✅ postgres-secret.yaml created!"
echo ""

echo "📝 Creating app-secrets.yaml..."
cat > manifests/security/app-secrets.yaml << EOF
apiVersion: v1
kind: Secret
metadata:
  name: tesslate-app-secrets
  namespace: tesslate
type: Opaque
stringData:
  # Core Application Secrets
  SECRET_KEY: "$SECRET_KEY"
  CSRF_SECRET_KEY: "$CSRF_SECRET"

  # Database Connection
  DATABASE_URL: "postgresql+asyncpg://tesslate_user:$POSTGRES_PASSWORD@postgres.tesslate.svc.cluster.local:5432/tesslate"

  # LiteLLM Configuration (from your .env.prod.copy)
  LITELLM_API_BASE: "https://apin.tesslate.com/v1"
  LITELLM_MASTER_KEY: "tesslateapi8819"
  LITELLM_DEFAULT_MODELS: "gpt-4o-mini,gpt-4o,gpt-3.5-turbo,claude-3-opus,claude-3-sonnet"
  LITELLM_TEAM_ID: "default"
  LITELLM_EMAIL_DOMAIN: "$APP_DOMAIN"
  LITELLM_INITIAL_BUDGET: "10.0"

  # Domain Configuration
  APP_DOMAIN: "$APP_DOMAIN"
  APP_PROTOCOL: "https"
  CORS_ORIGINS: "https://$APP_DOMAIN"
  ALLOWED_HOSTS: "$APP_DOMAIN,*.$APP_DOMAIN"
  COOKIE_DOMAIN: "$APP_DOMAIN"
  COOKIE_SECURE: "true"
  COOKIE_SAMESITE: "lax"

  # Deployment Mode
  DEPLOYMENT_MODE: "kubernetes"

  # Agent Resource Limits
  AGENT_MAX_COST: "20.0"
  AGENT_MAX_ITERATIONS: "100"
  AGENT_MAX_COST_PER_RUN: "5.0"

  # Container Cleanup Configuration
  CONTAINER_CLEANUP_INTERVAL_MINUTES: "2"
  CONTAINER_CLEANUP_TIER1_IDLE_MINUTES: "15"
  CONTAINER_CLEANUP_TIER2_PAUSED_HOURS: "24"

  # Kubernetes Configuration
  K8S_PVC_STORAGE_CLASS: "do-block-storage"
  K8S_PVC_SIZE: "5Gi"
  K8S_PVC_ACCESS_MODE: "ReadWriteOnce"
  K8S_NAMESPACE_PER_PROJECT: "true"
  K8S_ENABLE_NETWORK_POLICIES: "true"

  # OAuth Configuration (optional - can be added later)
  GOOGLE_CLIENT_ID: ""
  GOOGLE_CLIENT_SECRET: ""
  GOOGLE_OAUTH_REDIRECT_URI: "https://$APP_DOMAIN/api/auth/google/callback"
  GITHUB_CLIENT_ID: ""
  GITHUB_CLIENT_SECRET: ""
  GITHUB_OAUTH_REDIRECT_URI: "https://$APP_DOMAIN/api/auth/github/callback"

  # Stripe Configuration (optional - can be added later)
  STRIPE_SECRET_KEY: ""
  STRIPE_PUBLISHABLE_KEY: ""
  STRIPE_WEBHOOK_SECRET: ""
  STRIPE_PREMIUM_PRICE_ID: ""
  PREMIUM_SUBSCRIPTION_PRICE: "500"
  CREDIT_PACKAGE_SMALL: "500"
  CREDIT_PACKAGE_MEDIUM: "1500"
  CREDIT_PACKAGE_LARGE: "2500"
  FREE_MAX_PROJECTS: "1"
  PREMIUM_MAX_PROJECTS: "5"
EOF

echo "✅ app-secrets.yaml created!"
echo ""

echo "📝 Updating ClusterIssuer with your email..."
if [ -f "manifests/core/clusterissuer.yaml" ]; then
    sed -i.bak "s/your-email@example\.com/$SSL_EMAIL/g" manifests/core/clusterissuer.yaml
    rm -f manifests/core/clusterissuer.yaml.bak
    echo "✅ ClusterIssuer updated!"
else
    echo "⚠️  ClusterIssuer not found, skipping..."
fi

echo ""
echo "📝 Updating ingress with your domain..."
if [ -f "manifests/core/main-ingress.yaml" ]; then
    sed -i.bak "s/studio-test\.tesslate\.com/$APP_DOMAIN/g" manifests/core/main-ingress.yaml
    rm -f manifests/core/main-ingress.yaml.bak
    echo "✅ Ingress updated!"
else
    echo "⚠️  Ingress not found, skipping..."
fi

echo ""
echo "✅ All secrets generated successfully!"
echo ""
echo "📋 Files created:"
echo "   - manifests/security/postgres-secret.yaml"
echo "   - manifests/security/app-secrets.yaml"
echo ""
echo "🔒 Security Notes:"
echo "   ✅ All passwords are 32+ characters"
echo "   ✅ Passwords generated with cryptographically secure random"
echo "   ✅ Database password automatically matches in DATABASE_URL"
echo "   ✅ Files NOT committed to git (in .gitignore)"
echo ""
echo "⚠️  IMPORTANT: Save these passwords in your password manager!"
echo ""
echo "📊 Generated Credentials:"
echo "   PostgreSQL Password: $POSTGRES_PASSWORD"
echo "   (Other secrets stored in the YAML files)"
echo ""
echo "📋 Next Steps:"
echo "   1. Review the generated files in manifests/security/"
echo "   2. Add OAuth credentials if needed (Google, GitHub)"
echo "   3. Add Stripe credentials if needed"
echo "   4. Apply secrets to cluster:"
echo "      kubectl create namespace tesslate"
echo "      kubectl apply -f manifests/security/postgres-secret.yaml"
echo "      kubectl apply -f manifests/security/app-secrets.yaml"
echo "   5. Deploy application:"
echo "      cd scripts/deployment"
echo "      ./deploy-all.sh"
echo ""
