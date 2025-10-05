#!/bin/bash
# Setup Self-Hosted Docker Registry in Kubernetes
# This script deploys a Docker registry inside your cluster

set -e

echo "🚀 Setting up Self-Hosted Docker Registry..."

# Set kubeconfig
export KUBECONFIG=~/.kube/configs/digitalocean.yaml

# Check cluster connection
echo "📡 Checking cluster connection..."
kubectl cluster-info --request-timeout=10s

# Create namespaces
echo "📦 Creating namespaces..."
kubectl apply -f ../../manifests/base/01-namespaces.yaml

# Create storage classes (for DigitalOcean)
echo "💾 Setting up storage..."
kubectl apply -f ../../manifests/base/02-storage-class.yaml

# Deploy registry with DigitalOcean block storage
echo "🗃️  Deploying Docker registry..."
kubectl apply -f ../../manifests/registry/

# Wait for registry to be ready
echo "⏳ Waiting for registry to be ready..."
kubectl wait --for=condition=available --timeout=300s deployment/docker-registry -n tesslate-registry

# Check registry status
echo "✅ Registry Status:"
kubectl get pods,svc,pvc -n tesslate-registry

# Generate TLS certificates for registry security
echo "🔒 Generating TLS certificates for registry..."
mkdir -p /tmp/registry-certs
cd /tmp/registry-certs

# Create certificate configuration
cat > registry.conf << EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = US
ST = NY
L = NYC
O = Tesslate
CN = docker-registry.tesslate-registry.svc.cluster.local

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = docker-registry.tesslate-registry.svc.cluster.local
DNS.2 = docker-registry
IP.1 = $(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="ExternalIP")].address}')
IP.2 = $(kubectl get svc -n tesslate-registry docker-registry -o jsonpath='{.spec.clusterIP}')
EOF

# Generate certificate
openssl req -newkey rsa:4096 -nodes -sha256 -keyout registry.key \
  -x509 -days 365 -out registry.crt -config registry.conf -extensions v3_req

# Create Kubernetes TLS secret
echo "📝 Creating TLS secret for registry..."
kubectl create secret tls registry-tls --cert=registry.crt --key=registry.key -n tesslate-registry --dry-run=client -o yaml | kubectl apply -f -

# Create ConfigMap for CA bundle (for kubelet)
echo "📦 Creating CA configmap for kubelet..."
kubectl create configmap registry-ca --from-file=ca.crt=registry.crt -n tesslate-registry --dry-run=client -o yaml | kubectl apply -f -

# Apply TLS configuration
echo "🔧 Applying TLS configuration..."
kubectl apply -f ../../manifests/registry/04-registry-tls-config.yaml

# Update registry deployment to use TLS
echo "⚡ Updating registry deployment with TLS..."
kubectl apply -f ../../manifests/registry/02-registry-deployment.yaml

# Deploy kubelet CA trust configuration
echo "🔐 Installing CA trust for kubelet..."
kubectl apply -f ../../manifests/registry/05-kubelet-ca-trust.yaml

# Wait for registry to restart with TLS
echo "⏳ Waiting for registry to restart with TLS..."
kubectl wait --for=condition=available --timeout=300s deployment/docker-registry -n tesslate-registry

echo ""
echo "🎉 Secure Registry setup complete!"
echo ""
echo "Registry is available at:"
echo "  Internal HTTPS: docker-registry.tesslate-registry.svc.cluster.local:5000"
echo "  External HTTPS: $(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="ExternalIP")].address}'):30500"
echo ""
echo "⚠️  For Docker push, configure insecure registry in Docker Desktop:"
echo '  Add to Docker Engine: {"insecure-registries": ["<NODE-IP>:30500"]}'
echo ""
echo "Next: Run './02-build-push-images.sh' to build and push your images"