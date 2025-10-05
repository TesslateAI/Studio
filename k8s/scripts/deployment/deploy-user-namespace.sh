#!/bin/bash
# Deploy User Environments Namespace and Configuration
# This script sets up the separate namespace for user development environments

set -e

echo "🚀 Deploying User Environments Namespace..."

# Check prerequisites
echo "🔍 Checking prerequisites..."
if ! kubectl get namespace tesslate > /dev/null 2>&1; then
    echo "❌ Main tesslate namespace not found. Please run './deploy-application.sh' first"
    exit 1
fi

if ! kubectl get secret docr-secret -n tesslate > /dev/null 2>&1; then
    echo "❌ DOCR secret not found in tesslate namespace. Please run './setup-registry-auth.sh' first"
    exit 1
fi

# Check if cert-manager is installed
echo "🔍 Checking for cert-manager..."
if ! kubectl get namespace cert-manager > /dev/null 2>&1; then
    echo "⚠️  cert-manager not found. Installing cert-manager..."
    kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml
    echo "⏳ Waiting for cert-manager to be ready..."
    kubectl wait --for=condition=available --timeout=300s deployment/cert-manager -n cert-manager
    kubectl wait --for=condition=available --timeout=300s deployment/cert-manager-webhook -n cert-manager
    kubectl wait --for=condition=available --timeout=300s deployment/cert-manager-cainjector -n cert-manager
fi

# Check if letsencrypt-prod ClusterIssuer exists
echo "🔍 Checking for Let's Encrypt issuer..."
if ! kubectl get clusterissuer letsencrypt-prod > /dev/null 2>&1; then
    echo "⚠️  letsencrypt-prod ClusterIssuer not found. Creating..."
    cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@tesslate.com
    privateKeySecretRef:
      name: letsencrypt-prod-key
    solvers:
    - http01:
        ingress:
          class: nginx
EOF
    echo "✅ ClusterIssuer created"
fi

# Deploy user environments namespace and policies
echo "👥 Creating user environments namespace..."
kubectl apply -f ../../manifests/user-environments/namespace.yaml

# Wait for namespace to be ready
echo "⏳ Waiting for namespace to be ready..."
kubectl wait --for=jsonpath='{.status.phase}'=Active namespace/tesslate-user-environments --timeout=60s

# Deploy resource policies
echo "📋 Deploying resource policies and limits..."
kubectl apply -f ../../manifests/user-environments/resourcequota.yaml
kubectl apply -f ../../manifests/user-environments/limitrange.yaml
kubectl apply -f ../../manifests/user-environments/networkpolicy.yaml

# Deploy PVC for user projects
echo "💾 Creating shared storage for user projects..."
kubectl apply -f ../../manifests/user-environments/projects-pvc.yaml

# Wait for PVC to be bound
echo "⏳ Waiting for PVC to be bound..."
timeout 60 bash -c 'until kubectl get pvc tesslate-projects-pvc -n tesslate-user-environments -o jsonpath="{.status.phase}" | grep -q "Bound"; do sleep 2; done' || echo "⚠️  PVC binding is taking longer than expected (this is normal for first-time provisioning)"

# Update RBAC to include user environments namespace
echo "🔐 Updating RBAC permissions..."
kubectl apply -f ../../manifests/security/dev-environments-rbac.yaml

# Create registry secret in user environments namespace
echo "🔑 Creating registry secret in user environments namespace..."
if [ -z "$DOCR_TOKEN" ]; then
    echo "⚠️  DOCR_TOKEN not set, copying from tesslate namespace..."
    kubectl get secret docr-secret -n tesslate -o yaml | \
        sed 's/namespace: tesslate/namespace: tesslate-user-environments/' | \
        kubectl apply -f -
else
    kubectl create secret docker-registry docr-secret \
        --docker-server=registry.digitalocean.com \
        --docker-username=token \
        --docker-password="$DOCR_TOKEN" \
        --namespace=tesslate-user-environments \
        --dry-run=client -o yaml | kubectl apply -f -
fi

echo ""
echo "🎉 User environments namespace deployment complete!"
echo ""

# Show deployment status
echo "📊 Deployment Status:"
kubectl get namespace tesslate-user-environments
echo ""
kubectl get resourcequota,limitrange,networkpolicy -n tesslate-user-environments
echo ""

# Check certificate status
echo "🔒 Certificate Status:"
kubectl get certificate -n tesslate-user-environments
echo ""

# Show RBAC
echo "🔐 RBAC Status:"
kubectl get rolebinding tesslate-backend-user-environments -n tesslate-user-environments
echo ""

echo "✅ Setup Complete!"
echo ""
echo "The tesslate-user-environments namespace is ready for user development containers."
echo ""
echo "📋 Next Steps:"
echo "  1. Restart backend pods to pick up new configuration:"
echo "     kubectl rollout restart deployment/tesslate-backend -n tesslate"
echo ""
echo "  2. Verify wildcard certificate is issued:"
echo "     kubectl describe certificate tesslate-wildcard-cert -n tesslate-user-environments"
echo ""
echo "  3. Test creating a user environment through the API"
echo ""
echo "🔍 Useful commands:"
echo "  Check user environments: kubectl get all -n tesslate-user-environments"
echo "  View resource usage: kubectl top pods -n tesslate-user-environments"
echo "  Check network policies: kubectl describe networkpolicy -n tesslate-user-environments"
echo "  View quotas: kubectl describe resourcequota -n tesslate-user-environments"