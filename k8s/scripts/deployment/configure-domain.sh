#!/bin/bash
# Domain Configuration Helper for DigitalOcean Kubernetes Deployment
# This script updates all domain references in manifests and secrets

set -e

echo "🌐 Tesslate Studio - Domain Configuration Helper"
echo "================================================"
echo ""

# Check if domain is provided as argument
if [ -z "$1" ]; then
    echo "Please enter your domain (e.g., studio.yourdomain.com):"
    read -r DOMAIN
else
    DOMAIN=$1
fi

# Validate domain format
if [[ ! "$DOMAIN" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]*\.[a-zA-Z]{2,}$ ]]; then
    echo "❌ Error: Invalid domain format"
    echo "   Expected format: studio.yourdomain.com"
    exit 1
fi

echo ""
echo "🔧 Configuring domain: $DOMAIN"
echo ""

# Extract base domain for wildcard
BASE_DOMAIN=$(echo "$DOMAIN" | sed 's/^[^.]*\.//')
WILDCARD_DOMAIN="*.$DOMAIN"

# Confirmation
echo "📋 Configuration Summary:"
echo "   Main domain: $DOMAIN"
echo "   Wildcard domain: $WILDCARD_DOMAIN"
echo "   Base domain: $BASE_DOMAIN"
echo ""
read -p "Continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Configuration cancelled"
    exit 1
fi

echo ""
echo "🔄 Updating manifest files..."

# Navigate to manifests directory
MANIFESTS_DIR="$(cd "$(dirname "$0")/../../manifests" && pwd)"
cd "$MANIFESTS_DIR"

# Backup original files
echo "📦 Creating backups..."
find . -name "*.yaml" -type f ! -name "*.backup" -exec cp {} {}.backup \;

# Update ingress with new domain
echo "   ✓ Updating ingress configuration..."
sed -i.bak "s/studio-test\.tesslate\.com/$DOMAIN/g" core/main-ingress.yaml

# Update backend configmap if it exists
if [ -f "core/backend-configmap.yaml" ]; then
    echo "   ✓ Updating backend configmap..."
    sed -i.bak "s/studio-test\.tesslate\.com/$DOMAIN/g" core/backend-configmap.yaml
fi

# Update cluster issuer if it exists with email
if [ -f "core/clusterissuer.yaml" ]; then
    echo ""
    echo "📧 Please enter your email for Let's Encrypt notifications:"
    read -r EMAIL

    if [[ "$EMAIL" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
        echo "   ✓ Updating cluster issuer with email: $EMAIL"
        sed -i.bak "s/your-email@example\.com/$EMAIL/g" core/clusterissuer.yaml
    else
        echo "   ⚠ Invalid email format. Please update core/clusterissuer.yaml manually"
    fi
fi

# Clean up .bak files created by sed
find . -name "*.bak" -type f -delete

echo ""
echo "✅ Domain configuration complete!"
echo ""
echo "📋 Next steps:"
echo "   1. Review updated files in: $MANIFESTS_DIR"
echo "   2. Update secrets in: security/app-secrets.yaml"
echo "      - APP_DOMAIN: $DOMAIN"
echo "      - CORS_ORIGINS: https://$DOMAIN"
echo "      - ALLOWED_HOSTS: $DOMAIN,$WILDCARD_DOMAIN"
echo "      - COOKIE_DOMAIN: $DOMAIN"
echo "   3. Deploy with: cd ../scripts/deployment && ./deploy-all.sh"
echo ""
echo "📝 Don't forget to configure DNS after deployment:"
echo "   Type: A Record"
echo "   Name: $(echo "$DOMAIN" | cut -d'.' -f1)"
echo "   Value: <LOAD_BALANCER_IP>"
echo ""
echo "   Type: A Record"
echo "   Name: *.$(echo "$DOMAIN" | cut -d'.' -f1)"
echo "   Value: <LOAD_BALANCER_IP>"
echo ""
echo "💡 To restore backups if needed:"
echo "   find $MANIFESTS_DIR -name '*.backup' -exec bash -c 'mv \"\$1\" \"\${1%.backup}\"' _ {} \;"
