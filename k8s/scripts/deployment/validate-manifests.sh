#!/bin/bash
# Validate all Kubernetes manifests before deployment
# This script checks YAML syntax and required fields

set -e

echo "🔍 Validating Kubernetes Manifests"
echo "===================================="
echo ""

ERRORS=0
WARNINGS=0

# Function to check YAML syntax
check_yaml() {
    local file=$1
    if kubectl apply --dry-run=client -f "$file" &> /dev/null; then
        echo "✅ $file"
        return 0
    else
        echo "❌ $file - YAML VALIDATION FAILED"
        kubectl apply --dry-run=client -f "$file" 2>&1 | head -5
        return 1
    fi
}

# Function to check if domain is updated
check_domain() {
    local file=$1
    if grep -q "studio-test\.tesslate\.com" "$file" 2>/dev/null; then
        echo "⚠️  $file still contains old domain (studio-test.tesslate.com)"
        return 1
    fi
    return 0
}

# Check secrets exist
echo "1️⃣  Checking Secrets..."
if [ -f "../../manifests/security/app-secrets.yaml" ]; then
    if check_yaml "../../manifests/security/app-secrets.yaml"; then
        echo "   ✅ app-secrets.yaml exists and is valid"
    else
        ((ERRORS++))
    fi
else
    echo "   ❌ app-secrets.yaml NOT FOUND"
    ((ERRORS++))
fi

if [ -f "../../manifests/security/postgres-secret.yaml" ]; then
    if check_yaml "../../manifests/security/postgres-secret.yaml"; then
        echo "   ✅ postgres-secret.yaml exists and is valid"
    else
        ((ERRORS++))
    fi
else
    echo "   ❌ postgres-secret.yaml NOT FOUND"
    ((ERRORS++))
fi

echo ""
echo "2️⃣  Checking Base Infrastructure..."
for file in ../../manifests/base/*.yaml; do
    if [ -f "$file" ]; then
        check_yaml "$file" || ((ERRORS++))
    fi
done

echo ""
echo "3️⃣  Checking Database Manifests..."
for file in ../../manifests/database/*.yaml; do
    if [ -f "$file" ] && [[ ! "$file" =~ "secret" ]]; then
        check_yaml "$file" || ((ERRORS++))
    fi
done

echo ""
echo "4️⃣  Checking Core Application..."
for file in ../../manifests/core/*.yaml; do
    if [ -f "$file" ]; then
        check_yaml "$file" || ((ERRORS++))
        check_domain "$file" || ((WARNINGS++))
    fi
done

echo ""
echo "5️⃣  Checking Ingress Configuration..."
if [ -f "../../manifests/core/main-ingress.yaml" ]; then
    if check_yaml "../../manifests/core/main-ingress.yaml"; then
        # Check if domain is set to your-domain.com
        if grep -q "saipriya\.org" "../../manifests/core/main-ingress.yaml"; then
            echo "   ✅ Domain configured: your-domain.com"
        else
            echo "   ⚠️  Domain may not be configured correctly"
            ((WARNINGS++))
        fi
    else
        ((ERRORS++))
    fi
fi

echo ""
echo "6️⃣  Checking ClusterIssuer..."
if [ -f "../../manifests/core/clusterissuer.yaml" ]; then
    if check_yaml "../../manifests/core/clusterissuer.yaml"; then
        # Check if email is updated
        if grep -q "manav@tesslate\.com" "../../manifests/core/clusterissuer.yaml"; then
            echo "   ✅ Email configured: manav@tesslate.com"
        else
            echo "   ⚠️  Email may not be configured"
            ((WARNINGS++))
        fi
    else
        ((ERRORS++))
    fi
fi

echo ""
echo "7️⃣  Checking Security Resources..."
for file in ../../manifests/security/*-rbac.yaml; do
    if [ -f "$file" ]; then
        check_yaml "$file" || ((ERRORS++))
    fi
done

echo ""
echo "8️⃣  Checking Storage Configuration..."
if [ -f "../../manifests/storage/dynamic-storage-class.yaml" ]; then
    check_yaml "../../manifests/storage/dynamic-storage-class.yaml" || ((ERRORS++))
fi

echo ""
echo "9️⃣  Checking User Environments..."
for file in ../../manifests/user-environments/*.yaml; do
    if [ -f "$file" ]; then
        check_yaml "$file" || ((ERRORS++))
    fi
done

echo ""
echo "=" "=================================="
echo "📊 Validation Summary"
echo "===================================="
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo "✅ All manifests are valid!"
    echo ""
    echo "✅ Ready to deploy!"
    echo ""
    echo "Next steps:"
    echo "  1. Apply secrets:"
    echo "     kubectl create namespace tesslate"
    echo "     kubectl apply -f ../../manifests/security/postgres-secret.yaml"
    echo "     kubectl apply -f ../../manifests/security/app-secrets.yaml"
    echo ""
    echo "  2. Deploy application:"
    echo "     ./deploy-all.sh"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo "⚠️  $WARNINGS warnings found"
    echo ""
    echo "You can proceed with deployment, but review warnings above."
    echo ""
    read -p "Continue with deployment? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        exit 0
    else
        exit 1
    fi
else
    echo "❌ $ERRORS errors found"
    echo "❌ $WARNINGS warnings found"
    echo ""
    echo "Please fix the errors above before deploying."
    exit 1
fi
