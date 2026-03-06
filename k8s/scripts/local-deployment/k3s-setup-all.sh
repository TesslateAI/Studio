#!/bin/bash

# Tesslate Studio - Complete k3s Setup Script
# Much simpler than kubeadm, perfect for single-node production

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_IP=${1:-""}

echo "========================================"
echo "Tesslate Studio - k3s Setup"
echo "Simpler, lighter, production-ready!"
echo "========================================"

if [ -z "$SERVER_IP" ]; then
    echo "Usage: $0 <SERVER_IP>"
    echo "Example: $0 192.168.1.100"
    echo ""
    echo "This script will:"
    echo "  1. Install k3s (much faster than kubeadm)"
    echo "  2. Configure kubectl"
    echo "  3. Install NGINX Ingress (optional, k3s has Traefik)"
    echo "  4. Build application images"
    echo "  5. Deploy Tesslate Studio"
    exit 1
fi

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (use sudo)"
   exit 1
fi

echo ""
echo ">>> Installing k3s..."

# Install k3s with embedded registry and proper configuration
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server \
  --node-external-ip=$SERVER_IP \
  --bind-address=$SERVER_IP \
  --advertise-address=$SERVER_IP \
  --disable=traefik \
  --write-kubeconfig-mode=644" sh -

# Wait for k3s to be ready
echo "Waiting for k3s to be ready..."
sleep 10

# Verify k3s is running
systemctl status k3s --no-pager

# Set up kubectl for regular user
SUDO_USER_HOME=$(getent passwd $SUDO_USER | cut -d: -f6)
if [ ! -z "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
    mkdir -p $SUDO_USER_HOME/.kube
    cp /etc/rancher/k3s/k3s.yaml $SUDO_USER_HOME/.kube/config
    sed -i "s/127.0.0.1/$SERVER_IP/g" $SUDO_USER_HOME/.kube/config
    chown $SUDO_USER:$SUDO_USER $SUDO_USER_HOME/.kube/config
    chmod 600 $SUDO_USER_HOME/.kube/config
fi

# Set up kubectl for root
mkdir -p $HOME/.kube
cp /etc/rancher/k3s/k3s.yaml $HOME/.kube/config
sed -i "s/127.0.0.1/$SERVER_IP/g" $HOME/.kube/config

echo ""
echo ">>> Installing NGINX Ingress Controller..."
# Install NGINX Ingress (alternative to Traefik)
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.0/deploy/static/provider/cloud/deploy.yaml

# Wait for ingress to be ready
echo "Waiting for NGINX Ingress to be ready..."
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=300s

# Patch ingress to use NodePort instead of LoadBalancer
kubectl patch service ingress-nginx-controller -n ingress-nginx -p '{"spec":{"type":"NodePort","ports":[{"port":80,"targetPort":80,"nodePort":30080,"name":"http"},{"port":443,"targetPort":443,"nodePort":30443,"name":"https"}]}}'

echo ""
echo ">>> Creating data directories..."
mkdir -p /opt/k8s-data/{postgres,projects,registry}
chmod 755 /opt/k8s-data
chmod 755 /opt/k8s-data/*

echo ""
echo ">>> Building Docker images..."
bash $SCRIPT_DIR/build-images.sh

echo ""
echo ">>> Deploying Tesslate Studio..."
bash $SCRIPT_DIR/deploy-tesslate-k3s.sh

echo ""
echo "========================================"
echo "k3s Setup Complete!"
echo "========================================"
echo ""
echo "Tesslate Studio is now running on k3s!"
echo ""
echo "Access points:"
echo "  Web Interface: http://$SERVER_IP:30080"
echo "  API Endpoint: http://$SERVER_IP:30080/api"
echo ""
echo "k3s management:"
echo "  sudo systemctl status k3s"
echo "  sudo systemctl restart k3s"
echo "  kubectl get nodes"
echo "  kubectl get pods -A"
echo ""
echo "To uninstall k3s:"
echo "  /usr/local/bin/k3s-uninstall.sh"
echo "========================================"