#!/bin/bash

# Tesslate Studio - Phase 1: Server Preparation Script
# This script prepares a Ubuntu 22.04 server for Kubernetes installation

set -e

echo "========================================"
echo "Tesslate Studio Kubernetes Setup"
echo "Phase 1: Server Preparation"
echo "========================================"

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (use sudo)"
   exit 1
fi

# Update system
echo "[1/8] Updating system packages..."
apt update && apt upgrade -y

# Install required packages
echo "[2/8] Installing required packages..."
apt install -y curl wget apt-transport-https ca-certificates gnupg lsb-release \
    software-properties-common net-tools htop

# Disable swap
echo "[3/8] Disabling swap..."
swapoff -a
sed -i '/ swap / s/^\(.*\)$/#\1/g' /etc/fstab

# Load required kernel modules
echo "[4/8] Loading kernel modules..."
cat <<EOF | tee /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF

modprobe overlay
modprobe br_netfilter

# Configure sysctl params
echo "[5/8] Configuring sysctl parameters..."
cat <<EOF | tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF

sysctl --system

# Install containerd
echo "[6/8] Installing containerd..."
apt update
apt install -y containerd

# Configure containerd
echo "[7/8] Configuring containerd..."
mkdir -p /etc/containerd
containerd config default | tee /etc/containerd/config.toml

# Enable SystemdCgroup
sed -i 's/SystemdCgroup \= false/SystemdCgroup \= true/g' /etc/containerd/config.toml

# Restart and enable containerd
systemctl restart containerd
systemctl enable containerd

# Create data directories
echo "[8/8] Creating data directories..."
mkdir -p /opt/k8s-data/{postgres,projects,registry}
chmod 755 /opt/k8s-data
chmod 755 /opt/k8s-data/*

echo "========================================"
echo "Server preparation complete!"
echo "Next: Run 02-install-kubernetes.sh"
echo "========================================"