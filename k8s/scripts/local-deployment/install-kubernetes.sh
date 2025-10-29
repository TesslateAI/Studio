#!/bin/bash

# Tesslate Studio - Phase 1: Kubernetes Installation Script

set -e

echo "========================================"
echo "Tesslate Studio Kubernetes Setup"
echo "Phase 1: Install Kubernetes Components"
echo "========================================"

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (use sudo)"
   exit 1
fi

# Variables
K8S_VERSION="1.28"
SERVER_IP=${1:-""}

if [ -z "$SERVER_IP" ]; then
    echo "Usage: $0 <SERVER_IP>"
    echo "Example: $0 192.168.1.100"
    exit 1
fi

# Add Kubernetes APT repository
echo "[1/5] Adding Kubernetes APT repository..."
curl -fsSL https://pkgs.k8s.io/core:/stable:/v${K8S_VERSION}/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v${K8S_VERSION}/deb/ /" | tee /etc/apt/sources.list.d/kubernetes.list

# Install Kubernetes components
echo "[2/5] Installing Kubernetes components..."
apt update
apt install -y kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl

# Enable kubelet
echo "[3/5] Enabling kubelet service..."
systemctl enable kubelet

# Initialize Kubernetes cluster
echo "[4/5] Initializing Kubernetes cluster..."
kubeadm init --pod-network-cidr=10.244.0.0/16 --apiserver-advertise-address=$SERVER_IP

# Set up kubectl for regular user
echo "[5/5] Setting up kubectl for regular user..."
mkdir -p $HOME/.kube
cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
chown $(id -u):$(id -g) $HOME/.kube/config

# For non-root user setup
SUDO_USER_HOME=$(getent passwd $SUDO_USER | cut -d: -f6)
if [ ! -z "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
    mkdir -p $SUDO_USER_HOME/.kube
    cp -i /etc/kubernetes/admin.conf $SUDO_USER_HOME/.kube/config
    chown $SUDO_USER:$SUDO_USER $SUDO_USER_HOME/.kube/config
fi

echo "========================================"
echo "Kubernetes installation complete!"
echo "Next: Run 03-configure-cluster.sh"
echo "========================================"
echo ""
echo "Save this join command for adding worker nodes:"
kubeadm token create --print-join-command