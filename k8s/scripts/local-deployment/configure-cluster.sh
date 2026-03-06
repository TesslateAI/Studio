#!/bin/bash

# Tesslate Studio - Phase 1: Configure Kubernetes Cluster

set -e

echo "========================================"
echo "Tesslate Studio Kubernetes Setup"
echo "Phase 1: Configure Kubernetes Cluster"
echo "========================================"

# Remove taint from master node for single-node cluster
echo "[1/6] Removing taint from master node..."
kubectl taint nodes --all node-role.kubernetes.io/control-plane- 2>/dev/null || true

# Install Flannel CNI
echo "[2/6] Installing Flannel CNI..."
kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml

# Wait for Flannel to be ready
echo "Waiting for Flannel to be ready..."
sleep 10
kubectl wait --for=condition=ready pod -l app=flannel -n kube-flannel --timeout=300s

# Install Helm
echo "[3/6] Installing Helm..."
curl https://baltocdn.com/helm/signing.asc | gpg --dearmor | tee /usr/share/keyrings/helm.gpg > /dev/null
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/helm.gpg] https://baltocdn.com/helm/stable/debian/ all main" | tee /etc/apt/sources.list.d/helm-stable-debian.list
apt update
apt install -y helm

# Add Helm repositories
echo "[4/6] Adding Helm repositories..."
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add jetstack https://charts.jetstack.io
helm repo update

# Install NGINX Ingress Controller
echo "[5/6] Installing NGINX Ingress Controller..."
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.service.type=NodePort \
  --set controller.service.nodePorts.http=30080 \
  --set controller.service.nodePorts.https=30443 \
  --set controller.admissionWebhooks.enabled=false

# Install cert-manager (optional for SSL)
echo "[6/6] Installing cert-manager..."
kubectl create namespace cert-manager
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --set installCRDs=true

# Wait for pods to be ready
echo "Waiting for ingress-nginx to be ready..."
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=ingress-nginx -n ingress-nginx --timeout=300s

echo "Waiting for cert-manager to be ready..."
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=cert-manager -n cert-manager --timeout=300s

# Verify cluster status
echo ""
echo "========================================"
echo "Cluster Configuration Complete!"
echo "========================================"
echo ""
kubectl get nodes
echo ""
kubectl get pods -A
echo ""
echo "Ingress Controller is available at:"
echo "  HTTP: http://<SERVER_IP>:30080"
echo "  HTTPS: https://<SERVER_IP>:30443"
echo ""
echo "Next: Run 04-deploy-tesslate.sh"
echo "========================================"