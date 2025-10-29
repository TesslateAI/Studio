#!/bin/bash
# Verify Tesslate Studio Deployment
# This script checks that all components are properly deployed and configured

set -e

echo "🔍 Verifying Tesslate Studio Deployment..."
echo ""

# Set kubeconfig
export KUBECONFIG=~/.kube/configs/digitalocean.yaml

ERRORS=0
WARNINGS=0

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

function error() {
    echo -e "${RED}❌ $1${NC}"
    ERRORS=$((ERRORS + 1))
}

function success() {
    echo -e "${GREEN}✅ $1${NC}"
}

function warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
    WARNINGS=$((WARNINGS + 1))
}

# Check 1: Namespaces
echo "=== Checking Namespaces ==="
if kubectl get namespace tesslate > /dev/null 2>&1; then
    success "Main namespace (tesslate) exists"
else
    error "Main namespace (tesslate) not found"
fi

if kubectl get namespace tesslate-user-environments > /dev/null 2>&1; then
    success "User environments namespace exists"
else
    error "User environments namespace not found"
fi
echo ""

# Check 2: RBAC
echo "=== Checking RBAC Configuration ==="
if kubectl get serviceaccount tesslate-backend-sa -n tesslate > /dev/null 2>&1; then
    success "Backend ServiceAccount exists"
else
    error "Backend ServiceAccount not found"
fi

if kubectl get clusterrole tesslate-dev-environments-manager > /dev/null 2>&1; then
    success "ClusterRole exists"
else
    error "ClusterRole not found"
fi

if kubectl get rolebinding tesslate-backend-user-environments -n tesslate-user-environments > /dev/null 2>&1; then
    success "RoleBinding in user-environments namespace exists"
else
    error "RoleBinding in user-environments namespace not found"
fi

# Test RBAC permissions
echo "Testing RBAC permissions..."
CAN_CREATE_DEPLOY=$(kubectl auth can-i create deployments --as=system:serviceaccount:tesslate:tesslate-backend-sa -n tesslate-user-environments 2>/dev/null)
if [ "$CAN_CREATE_DEPLOY" == "yes" ]; then
    success "Backend can create deployments in user-environments"
else
    error "Backend CANNOT create deployments in user-environments"
fi

CAN_CREATE_SVC=$(kubectl auth can-i create services --as=system:serviceaccount:tesslate:tesslate-backend-sa -n tesslate-user-environments 2>/dev/null)
if [ "$CAN_CREATE_SVC" == "yes" ]; then
    success "Backend can create services in user-environments"
else
    error "Backend CANNOT create services in user-environments"
fi

CAN_CREATE_ING=$(kubectl auth can-i create ingresses --as=system:serviceaccount:tesslate:tesslate-backend-sa -n tesslate-user-environments 2>/dev/null)
if [ "$CAN_CREATE_ING" == "yes" ]; then
    success "Backend can create ingresses in user-environments"
else
    error "Backend CANNOT create ingresses in user-environments"
fi
echo ""

# Check 3: Secrets
echo "=== Checking Secrets ==="
if kubectl get secret docr-secret -n tesslate > /dev/null 2>&1; then
    success "Registry secret exists in tesslate namespace"
else
    error "Registry secret not found in tesslate namespace"
fi

if kubectl get secret docr-secret -n tesslate-user-environments > /dev/null 2>&1; then
    success "Registry secret exists in user-environments namespace"
else
    error "Registry secret not found in user-environments namespace"
fi

if kubectl get secret tesslate-app-secrets -n tesslate > /dev/null 2>&1; then
    success "Application secrets exist"
else
    error "Application secrets not found"
fi
echo ""

# Check 4: PVCs
echo "=== Checking Storage ==="
BACKEND_PVC_STATUS=$(kubectl get pvc tesslate-backend-templates-pvc -n tesslate -o jsonpath='{.status.phase}' 2>/dev/null || echo "NotFound")
if [ "$BACKEND_PVC_STATUS" == "Bound" ]; then
    success "Backend templates PVC is bound"
elif [ "$BACKEND_PVC_STATUS" == "Pending" ]; then
    warning "Backend templates PVC is pending"
elif [ "$BACKEND_PVC_STATUS" == "NotFound" ]; then
    warning "Backend templates PVC not found (may not be needed)"
else
    error "Backend templates PVC status: $BACKEND_PVC_STATUS"
fi

USER_PVC_STATUS=$(kubectl get pvc tesslate-projects-pvc -n tesslate-user-environments -o jsonpath='{.status.phase}' 2>/dev/null || echo "NotFound")
if [ "$USER_PVC_STATUS" == "Bound" ]; then
    success "User projects PVC is bound"
elif [ "$USER_PVC_STATUS" == "Pending" ]; then
    warning "User projects PVC is pending (may take a few minutes)"
elif [ "$USER_PVC_STATUS" == "NotFound" ]; then
    error "User projects PVC not found"
else
    error "User projects PVC status: $USER_PVC_STATUS"
fi

# Check storage class
SC_NAME=$(kubectl get pvc tesslate-projects-pvc -n tesslate-user-environments -o jsonpath='{.spec.storageClassName}' 2>/dev/null || echo "")
if [ "$SC_NAME" == "do-block-storage" ]; then
    success "Using correct StorageClass: $SC_NAME"
elif [ -n "$SC_NAME" ]; then
    warning "Using StorageClass: $SC_NAME (expected: do-block-storage)"
fi
echo ""

# Check 5: Deployments
echo "=== Checking Application Deployments ==="
BACKEND_STATUS=$(kubectl get deployment tesslate-backend -n tesslate -o jsonpath='{.status.conditions[?(@.type=="Available")].status}' 2>/dev/null || echo "NotFound")
if [ "$BACKEND_STATUS" == "True" ]; then
    success "Backend deployment is available"
    BACKEND_READY=$(kubectl get deployment tesslate-backend -n tesslate -o jsonpath='{.status.readyReplicas}')
    BACKEND_DESIRED=$(kubectl get deployment tesslate-backend -n tesslate -o jsonpath='{.status.replicas}')
    echo "   Ready: $BACKEND_READY/$BACKEND_DESIRED replicas"
else
    error "Backend deployment not available"
fi

FRONTEND_STATUS=$(kubectl get deployment tesslate-frontend -n tesslate -o jsonpath='{.status.conditions[?(@.type=="Available")].status}' 2>/dev/null || echo "NotFound")
if [ "$FRONTEND_STATUS" == "True" ]; then
    success "Frontend deployment is available"
    FRONTEND_READY=$(kubectl get deployment tesslate-frontend -n tesslate -o jsonpath='{.status.readyReplicas}')
    FRONTEND_DESIRED=$(kubectl get deployment tesslate-frontend -n tesslate -o jsonpath='{.status.replicas}')
    echo "   Ready: $FRONTEND_READY/$FRONTEND_DESIRED replicas"
else
    error "Frontend deployment not available"
fi
echo ""

# Check 6: Ingress
echo "=== Checking Ingress Configuration ==="
if kubectl get ingress -n tesslate > /dev/null 2>&1; then
    INGRESS_COUNT=$(kubectl get ingress -n tesslate --no-headers 2>/dev/null | wc -l)
    success "Found $INGRESS_COUNT ingress(es) in tesslate namespace"
else
    warning "No ingresses found in tesslate namespace"
fi

# Check NGINX Ingress Controller
if kubectl get namespace ingress-nginx > /dev/null 2>&1; then
    success "NGINX Ingress Controller namespace exists"
    NGINX_STATUS=$(kubectl get deployment ingress-nginx-controller -n ingress-nginx -o jsonpath='{.status.conditions[?(@.type=="Available")].status}' 2>/dev/null || echo "NotFound")
    if [ "$NGINX_STATUS" == "True" ]; then
        success "NGINX Ingress Controller is running"
    else
        error "NGINX Ingress Controller not available"
    fi
else
    error "NGINX Ingress Controller not installed"
fi

# Check Load Balancer IP
LB_IP=$(kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
if [ -n "$LB_IP" ]; then
    success "Load Balancer IP assigned: $LB_IP"
else
    warning "Load Balancer IP not yet assigned (may be pending)"
fi
echo ""

# Check 7: SSL/TLS
echo "=== Checking SSL Configuration ==="
if kubectl get namespace cert-manager > /dev/null 2>&1; then
    success "cert-manager is installed"

    if kubectl get clusterissuer letsencrypt-prod > /dev/null 2>&1; then
        success "Let's Encrypt ClusterIssuer exists"
    else
        warning "Let's Encrypt ClusterIssuer not found"
    fi

    CERT_STATUS=$(kubectl get certificate tesslate-wildcard-cert -n tesslate-user-environments -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "NotFound")
    if [ "$CERT_STATUS" == "True" ]; then
        success "Wildcard SSL certificate is ready"
    elif [ "$CERT_STATUS" == "NotFound" ]; then
        warning "Wildcard SSL certificate not found"
    else
        warning "Wildcard SSL certificate not ready yet (may take a few minutes)"
    fi
else
    warning "cert-manager not installed (SSL certificates will not be automatically issued)"
fi
echo ""

# Check 8: User Environments
echo "=== Checking User Development Environments ==="
USER_ENV_COUNT=$(kubectl get deployments -n tesslate-user-environments -l app=dev-environment --no-headers 2>/dev/null | wc -l)
if [ "$USER_ENV_COUNT" -gt 0 ]; then
    success "Found $USER_ENV_COUNT user development environment(s)"
    kubectl get deployments,services,ingresses -n tesslate-user-environments -l app=dev-environment
else
    echo "   No user environments currently running (this is normal)"
fi
echo ""

# Summary
echo "========================================="
echo "📊 Verification Summary"
echo "========================================="
if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✅ All checks passed! Deployment is healthy.${NC}"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  Deployment is functional but has $WARNINGS warning(s).${NC}"
    exit 0
else
    echo -e "${RED}❌ Found $ERRORS error(s) and $WARNINGS warning(s).${NC}"
    echo ""
    echo "Please review the errors above and take corrective action."
    echo "Common fixes:"
    echo "  - Run: kubectl apply -f ../../manifests/security/dev-environments-rbac.yaml"
    echo "  - Run: ./01-setup-registry-auth.sh (if secrets missing)"
    echo "  - Run: ./05-deploy-user-namespace.sh (if user namespace issues)"
    exit 1
fi