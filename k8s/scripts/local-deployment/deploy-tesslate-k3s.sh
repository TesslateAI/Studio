#!/bin/bash

# Tesslate Studio - Deploy Application to k3s

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFESTS_DIR="$(dirname "$SCRIPT_DIR")/manifests"

echo "========================================"
echo "Tesslate Studio k3s Deployment"
echo "========================================"

# Check if kubectl is configured
if ! kubectl cluster-info &> /dev/null; then
    echo "Error: kubectl is not configured or cluster is not accessible"
    exit 1
fi

# Create k3s-compatible storage class (k3s uses local-path by default)
echo "[1/7] Creating k3s storage class..."
cat <<EOF | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: tesslate-local-storage
  annotations:
    storageclass.kubernetes.io/is-default-class: "false"
provisioner: rancher.io/local-path
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
allowVolumeExpansion: true
EOF

# Deploy base infrastructure (skip PVs, k3s handles them automatically)
echo "[2/7] Deploying base infrastructure..."
kubectl apply -f $MANIFESTS_DIR/base/01-namespaces.yaml
kubectl apply -f $MANIFESTS_DIR/base/04-network-policies.yaml

# Wait for namespaces
sleep 5

# Deploy PostgreSQL database (k3s will auto-create PVs)
echo "[3/7] Deploying PostgreSQL database..."
kubectl apply -f $MANIFESTS_DIR/database/

# Wait for database to be ready
echo "Waiting for PostgreSQL to be ready..."
kubectl wait --for=condition=ready pod -l app=postgres -n tesslate --timeout=300s

# Deploy application secrets and configs
echo "[4/7] Deploying application configuration..."
kubectl apply -f $MANIFESTS_DIR/app/01-app-secrets.yaml
kubectl apply -f $MANIFESTS_DIR/app/02-backend-configmap.yaml

# Deploy application (backend and frontend)
echo "[5/7] Deploying Tesslate application..."
kubectl apply -f $MANIFESTS_DIR/app/04-backend-deployment.yaml
kubectl apply -f $MANIFESTS_DIR/app/05-frontend-deployment.yaml
kubectl apply -f $MANIFESTS_DIR/app/06-backend-service.yaml
kubectl apply -f $MANIFESTS_DIR/app/07-frontend-service.yaml

# Create k3s-compatible ingress
echo "[6/7] Creating ingress configuration..."
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: tesslate-ingress
  namespace: tesslate
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /\$2
    nginx.ingress.kubernetes.io/proxy-body-size: "50m"
    nginx.ingress.kubernetes.io/proxy-connect-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
spec:
  ingressClassName: nginx
  rules:
  - host: tesslate.local
    http:
      paths:
      - path: /api(/|$)(.*)
        pathType: Prefix
        backend:
          service:
            name: tesslate-backend-service
            port:
              number: 8005
      - path: /
        pathType: Prefix
        backend:
          service:
            name: tesslate-frontend-service
            port:
              number: 80
  - host: localhost
    http:
      paths:
      - path: /api(/|$)(.*)
        pathType: Prefix
        backend:
          service:
            name: tesslate-backend-service
            port:
              number: 8005
      - path: /
        pathType: Prefix
        backend:
          service:
            name: tesslate-frontend-service
            port:
              number: 80
EOF

# Wait for deployments to be ready
echo "[7/7] Waiting for application to be ready..."
kubectl wait --for=condition=available deployment/tesslate-backend -n tesslate --timeout=300s
kubectl wait --for=condition=available deployment/tesslate-frontend -n tesslate --timeout=300s

# Show deployment status
echo ""
echo "Deployment Status:"
echo ""
echo "Namespaces:"
kubectl get namespaces | grep tesslate

echo ""
echo "Pods:"
kubectl get pods -n tesslate

echo ""
echo "Services:"
kubectl get services -n tesslate

echo ""
echo "Ingress:"
kubectl get ingress -n tesslate

echo ""
echo "Storage:"
kubectl get pvc -n tesslate
kubectl get storageclass

echo ""
echo "========================================"
echo "k3s Deployment Complete!"
echo "========================================"
echo ""
echo "Access the application at:"
SERVER_IP=$(kubectl get node -o jsonpath='{.items[0].status.addresses[?(@.type=="ExternalIP")].address}')
if [ -z "$SERVER_IP" ]; then
    SERVER_IP=$(kubectl get node -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
fi
echo "  http://$SERVER_IP:30080"
echo "  or configure /etc/hosts with: $SERVER_IP tesslate.local"
echo "  then access: http://tesslate.local:30080"
echo ""
echo "k3s specific commands:"
echo "  sudo systemctl status k3s"
echo "  kubectl get nodes"
echo "  kubectl get pods -A"
echo ""
echo "To check logs:"
echo "  kubectl logs -f deployment/tesslate-backend -n tesslate"
echo "  kubectl logs -f deployment/tesslate-frontend -n tesslate"
echo "========================================"