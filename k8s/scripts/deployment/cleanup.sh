#!/bin/bash
# Cleanup OpenSail Deployment
# This script removes all deployed resources

set -e

echo "🧹 OpenSail Cleanup Script"
echo ""
echo "⚠️  WARNING: This will DELETE all Tesslate resources including:"
echo "  - All application pods and services"
echo "  - Database and all data"
echo "  - Docker registry and stored images"
echo "  - Persistent storage volumes"
echo ""

# Confirm before proceeding
read -p "Are you sure you want to continue? (type 'DELETE' to confirm): " confirm
if [ "$confirm" != "DELETE" ]; then
    echo "Cleanup cancelled"
    exit 1
fi

# Set kubeconfig
export KUBECONFIG=~/.kube/configs/digitalocean.yaml

echo "🗑️  Deleting application resources..."
kubectl delete -f ../../manifests/app/ --ignore-not-found=true

echo "🗑️  Deleting database resources..."
kubectl delete -f ../../manifests/database/ --ignore-not-found=true

echo "🗑️  Deleting registry resources..."
kubectl delete -f ../../manifests/registry/ --ignore-not-found=true

echo "🗑️  Deleting base resources..."
kubectl delete -f ../../manifests/base/ --ignore-not-found=true

echo "🗑️  Deleting secrets..."
kubectl delete secret tesslate-app-secrets postgres-secret -n tesslate --ignore-not-found=true

echo "🗑️  Deleting NGINX ingress controller..."
kubectl delete -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.1/deploy/static/provider/do/deploy.yaml --ignore-not-found=true

echo ""
echo "🎉 Cleanup complete!"
echo ""
echo "All OpenSail resources have been removed from your cluster."
echo "Your DigitalOcean Kubernetes cluster itself remains running."