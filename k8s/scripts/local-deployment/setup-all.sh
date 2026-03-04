#!/bin/bash

# Tesslate Studio - Complete Setup Script
# This script runs all phases to set up Tesslate Studio on Kubernetes

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_IP=${1:-""}

echo "========================================"
echo "Tesslate Studio - Complete Kubernetes Setup"
echo "========================================"

if [ -z "$SERVER_IP" ]; then
    echo "Usage: $0 <SERVER_IP>"
    echo "Example: $0 192.168.1.100"
    echo ""
    echo "This script will:"
    echo "  1. Prepare the server"
    echo "  2. Install Kubernetes"
    echo "  3. Configure the cluster"
    echo "  4. Build application images"
    echo "  5. Deploy Tesslate Studio"
    exit 1
fi

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (use sudo)"
   exit 1
fi

# Phase 1: Server Preparation
echo ""
echo ">>> Phase 1: Server Preparation"
bash $SCRIPT_DIR/01-prepare-server.sh

# Phase 2: Install Kubernetes
echo ""
echo ">>> Phase 2: Installing Kubernetes"
bash $SCRIPT_DIR/02-install-kubernetes.sh $SERVER_IP

# Phase 3: Configure Cluster
echo ""
echo ">>> Phase 3: Configuring Cluster"
bash $SCRIPT_DIR/03-configure-cluster.sh

# Phase 4: Build Images
echo ""
echo ">>> Phase 4: Building Docker Images"
bash $SCRIPT_DIR/build-images.sh

# Phase 5: Deploy Application
echo ""
echo ">>> Phase 5: Deploying Tesslate Studio"
bash $SCRIPT_DIR/04-deploy-tesslate.sh

echo ""
echo "========================================"
echo "Setup Complete!"
echo "========================================"
echo ""
echo "Tesslate Studio is now running on Kubernetes!"
echo ""
echo "Access points:"
echo "  Web Interface: http://$SERVER_IP:30080"
echo "  API Endpoint: http://$SERVER_IP:30080/api"
echo "  Docker Registry: $SERVER_IP:30500"
echo ""
echo "Useful commands:"
echo "  kubectl get pods -n tesslate"
echo "  kubectl logs -f deployment/tesslate-backend -n tesslate"
echo "  kubectl exec -it deployment/postgres -n tesslate -- psql -U tesslate_user tesslate"
echo ""
echo "========================================"