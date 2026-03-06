#!/bin/bash
# =============================================================================
# Tesslate Studio - Pod Affinity Test Script
# =============================================================================
# This script tests pod affinity for multi-container projects:
# 1. Creates a test project with multiple containers
# 2. Verifies all pods are scheduled on the same node
# 3. Tests shared PVC access from multiple pods
#
# Usage:
#   ./test-pod-affinity.sh
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
NAMESPACE="tesslate-affinity-test"
PROJECT_ID="affinity-test-$(date +%s)"

echo -e "${BLUE}=============================================${NC}"
echo -e "${BLUE}  Pod Affinity Test${NC}"
echo -e "${BLUE}=============================================${NC}"
echo ""

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1"
}

log_test() {
    echo -e "${YELLOW}[TEST]${NC} $1"
}

# =============================================================================
# Test 1: Create Namespace and Shared PVC
# =============================================================================

log_test "Creating namespace and shared PVC..."

kubectl apply -f - <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: $NAMESPACE
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: shared-project-pvc
  namespace: $NAMESPACE
  labels:
    project-id: $PROJECT_ID
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: tesslate-block-storage
  resources:
    requests:
      storage: 1Gi
EOF

log_success "Namespace and PVC created"

# =============================================================================
# Test 2: Deploy First Container (Frontend)
# =============================================================================

log_test "Deploying first container (frontend)..."

kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend
  namespace: $NAMESPACE
  labels:
    app: frontend
    project-id: $PROJECT_ID
spec:
  replicas: 1
  selector:
    matchLabels:
      app: frontend
  template:
    metadata:
      labels:
        app: frontend
        project-id: $PROJECT_ID
        storage-mode: shared-pvc
        affinity-anchor: "true"
    spec:
      containers:
      - name: frontend
        image: node:20-alpine
        command: ["sleep", "3600"]
        volumeMounts:
        - name: shared-project
          mountPath: /app
      volumes:
      - name: shared-project
        persistentVolumeClaim:
          claimName: shared-project-pvc
EOF

# Wait for frontend to be ready
log_info "Waiting for frontend pod..."
kubectl wait --for=condition=ready pod -l app=frontend -n "$NAMESPACE" --timeout=120s

log_success "Frontend container deployed"

# Get the node where frontend is running
FRONTEND_NODE=$(kubectl get pod -l app=frontend -n "$NAMESPACE" -o jsonpath='{.items[0].spec.nodeName}')
log_info "Frontend running on node: $FRONTEND_NODE"

# =============================================================================
# Test 3: Deploy Second Container (Backend) with Pod Affinity
# =============================================================================

log_test "Deploying second container (backend) with pod affinity..."

kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend
  namespace: $NAMESPACE
  labels:
    app: backend
    project-id: $PROJECT_ID
spec:
  replicas: 1
  selector:
    matchLabels:
      app: backend
  template:
    metadata:
      labels:
        app: backend
        project-id: $PROJECT_ID
        storage-mode: shared-pvc
    spec:
      affinity:
        podAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchLabels:
                project-id: $PROJECT_ID
                storage-mode: shared-pvc
            topologyKey: kubernetes.io/hostname
      containers:
      - name: backend
        image: node:20-alpine
        command: ["sleep", "3600"]
        volumeMounts:
        - name: shared-project
          mountPath: /app
      volumes:
      - name: shared-project
        persistentVolumeClaim:
          claimName: shared-project-pvc
EOF

# Wait for backend to be ready
log_info "Waiting for backend pod..."
kubectl wait --for=condition=ready pod -l app=backend -n "$NAMESPACE" --timeout=120s

log_success "Backend container deployed"

# Get the node where backend is running
BACKEND_NODE=$(kubectl get pod -l app=backend -n "$NAMESPACE" -o jsonpath='{.items[0].spec.nodeName}')
log_info "Backend running on node: $BACKEND_NODE"

# =============================================================================
# Test 4: Verify Both Pods on Same Node
# =============================================================================

log_test "Verifying pods are on the same node..."

if [ "$FRONTEND_NODE" = "$BACKEND_NODE" ]; then
    log_success "Both pods are on the same node: $FRONTEND_NODE"
else
    log_error "Pods are on different nodes! Frontend: $FRONTEND_NODE, Backend: $BACKEND_NODE"
    exit 1
fi

# =============================================================================
# Test 5: Test Shared PVC Access
# =============================================================================

log_test "Testing shared PVC access..."

# Write from frontend
FRONTEND_POD=$(kubectl get pod -l app=frontend -n "$NAMESPACE" -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n "$NAMESPACE" "$FRONTEND_POD" -- sh -c 'echo "Hello from frontend" > /app/frontend.txt'
log_success "Frontend wrote to shared PVC"

# Read from backend
BACKEND_POD=$(kubectl get pod -l app=backend -n "$NAMESPACE" -o jsonpath='{.items[0].metadata.name}')
CONTENT=$(kubectl exec -n "$NAMESPACE" "$BACKEND_POD" -- cat /app/frontend.txt)
if echo "$CONTENT" | grep -q "Hello from frontend"; then
    log_success "Backend can read frontend's file from shared PVC"
else
    log_error "Backend cannot read from shared PVC"
    exit 1
fi

# Write from backend
kubectl exec -n "$NAMESPACE" "$BACKEND_POD" -- sh -c 'echo "Hello from backend" > /app/backend.txt'
log_success "Backend wrote to shared PVC"

# Read from frontend
CONTENT=$(kubectl exec -n "$NAMESPACE" "$FRONTEND_POD" -- cat /app/backend.txt)
if echo "$CONTENT" | grep -q "Hello from backend"; then
    log_success "Frontend can read backend's file from shared PVC"
else
    log_error "Frontend cannot read from shared PVC"
    exit 1
fi

# =============================================================================
# Test 6: Deploy Third Container (Database) with Pod Affinity
# =============================================================================

log_test "Deploying third container (database) with pod affinity..."

kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: database
  namespace: $NAMESPACE
  labels:
    app: database
    project-id: $PROJECT_ID
spec:
  replicas: 1
  selector:
    matchLabels:
      app: database
  template:
    metadata:
      labels:
        app: database
        project-id: $PROJECT_ID
        storage-mode: shared-pvc
    spec:
      affinity:
        podAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchLabels:
                project-id: $PROJECT_ID
                storage-mode: shared-pvc
            topologyKey: kubernetes.io/hostname
      containers:
      - name: database
        image: postgres:15-alpine
        env:
        - name: POSTGRES_PASSWORD
          value: testpassword
        volumeMounts:
        - name: shared-project
          mountPath: /app
          subPath: data
      volumes:
      - name: shared-project
        persistentVolumeClaim:
          claimName: shared-project-pvc
EOF

# Wait for database to be ready
log_info "Waiting for database pod..."
sleep 5  # Give it a moment to schedule
kubectl wait --for=condition=ready pod -l app=database -n "$NAMESPACE" --timeout=120s 2>/dev/null || {
    log_info "Database may still be starting, checking node..."
}

# Get the node where database is running
DB_NODE=$(kubectl get pod -l app=database -n "$NAMESPACE" -o jsonpath='{.items[0].spec.nodeName}')
log_info "Database running on node: $DB_NODE"

# Verify all on same node
if [ "$FRONTEND_NODE" = "$DB_NODE" ]; then
    log_success "All three pods are on the same node: $FRONTEND_NODE"
else
    log_error "Database is on a different node! Expected: $FRONTEND_NODE, Got: $DB_NODE"
    exit 1
fi

# =============================================================================
# Cleanup
# =============================================================================

log_info "Cleaning up test resources..."
kubectl delete namespace "$NAMESPACE" --ignore-not-found=true &

# =============================================================================
# Summary
# =============================================================================

echo ""
echo -e "${GREEN}=============================================${NC}"
echo -e "${GREEN}  All Pod Affinity Tests Passed!${NC}"
echo -e "${GREEN}=============================================${NC}"
echo ""
echo "Tests completed:"
echo "  ✓ Namespace and shared PVC creation"
echo "  ✓ First container (frontend) deployment"
echo "  ✓ Second container (backend) with pod affinity"
echo "  ✓ Both pods scheduled on same node"
echo "  ✓ Shared PVC read/write from frontend"
echo "  ✓ Shared PVC read/write from backend"
echo "  ✓ Third container (database) with pod affinity"
echo "  ✓ All three pods on same node"
echo ""
echo "Pod Affinity Summary:"
echo "  All containers in project: $PROJECT_ID"
echo "  Were scheduled on node: $FRONTEND_NODE"
echo "  Shared PVC: shared-project-pvc (RWO)"
echo ""
