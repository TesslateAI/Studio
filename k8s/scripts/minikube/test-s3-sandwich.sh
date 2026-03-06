#!/bin/bash
# =============================================================================
# Tesslate Studio - S3 Sandwich Test Script
# =============================================================================
# This script tests the S3 Sandwich pattern:
# 1. Creates a test project
# 2. Writes files to the project
# 3. Triggers dehydration (upload to S3)
# 4. Verifies files in S3
# 5. Recreates project (hydration from S3)
# 6. Verifies files are restored
#
# Usage:
#   ./test-s3-sandwich.sh
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
NAMESPACE="tesslate-test-project"
PROJECT_ID="test-$(date +%s)"
USER_ID="test-user-12345678"

echo -e "${BLUE}=============================================${NC}"
echo -e "${BLUE}  S3 Sandwich Test${NC}"
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
# Test 1: MinIO Connectivity
# =============================================================================

log_test "Testing MinIO connectivity..."

MINIO_POD=$(kubectl get pod -n minio-system -l app=minio -o jsonpath='{.items[0].metadata.name}')
if [ -z "$MINIO_POD" ]; then
    log_error "MinIO pod not found"
    exit 1
fi

# Check if bucket exists
if kubectl exec -n minio-system "$MINIO_POD" -- mc ls local/tesslate-projects 2>/dev/null; then
    log_success "MinIO bucket 'tesslate-projects' exists"
else
    log_info "Creating bucket..."
    kubectl exec -n minio-system "$MINIO_POD" -- mc mb local/tesslate-projects 2>/dev/null || true
    log_success "Bucket created"
fi

# =============================================================================
# Test 2: Create Test Namespace and PVC
# =============================================================================

log_test "Creating test namespace and PVC..."

kubectl apply -f - <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: $NAMESPACE
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: project-source
  namespace: $NAMESPACE
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
# Test 3: Create Test Pod with Project Files
# =============================================================================

log_test "Creating test pod with sample files..."

kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: test-dev-server
  namespace: $NAMESPACE
  labels:
    app: test-dev-server
    project-id: $PROJECT_ID
spec:
  containers:
  - name: dev-server
    image: node:20-alpine
    command: ["sleep", "3600"]
    volumeMounts:
    - name: project-source
      mountPath: /app
    env:
    - name: S3_ACCESS_KEY_ID
      valueFrom:
        secretKeyRef:
          name: s3-credentials
          key: S3_ACCESS_KEY_ID
          optional: true
    - name: S3_SECRET_ACCESS_KEY
      valueFrom:
        secretKeyRef:
          name: s3-credentials
          key: S3_SECRET_ACCESS_KEY
          optional: true
  volumes:
  - name: project-source
    persistentVolumeClaim:
      claimName: project-source
EOF

# Copy S3 credentials to test namespace
kubectl get secret s3-credentials -n tesslate -o yaml | \
    sed "s/namespace: tesslate/namespace: $NAMESPACE/" | \
    kubectl apply -f - 2>/dev/null || log_info "S3 credentials secret may already exist"

# Wait for pod to be ready
log_info "Waiting for pod to be ready..."
kubectl wait --for=condition=ready pod/test-dev-server -n "$NAMESPACE" --timeout=120s

log_success "Test pod created"

# =============================================================================
# Test 4: Write Test Files
# =============================================================================

log_test "Writing test files to project..."

kubectl exec -n "$NAMESPACE" test-dev-server -- sh -c '
cat > /app/package.json << "EOF"
{
  "name": "test-project",
  "version": "1.0.0",
  "description": "S3 Sandwich test project"
}
EOF
'

kubectl exec -n "$NAMESPACE" test-dev-server -- sh -c '
cat > /app/index.js << "EOF"
console.log("Hello from S3 Sandwich!");
EOF
'

kubectl exec -n "$NAMESPACE" test-dev-server -- sh -c '
mkdir -p /app/src
cat > /app/src/app.js << "EOF"
export function greet(name) {
  return "Hello, " + name + "!";
}
EOF
'

# Verify files were created
FILES=$(kubectl exec -n "$NAMESPACE" test-dev-server -- ls /app)
if echo "$FILES" | grep -q "package.json"; then
    log_success "Test files created successfully"
else
    log_error "Failed to create test files"
    exit 1
fi

# =============================================================================
# Test 5: Simulate Dehydration (Upload to S3)
# =============================================================================

log_test "Testing dehydration (upload to S3)..."

# Install aws-cli in the pod
kubectl exec -n "$NAMESPACE" test-dev-server -- sh -c '
apk add --no-cache aws-cli zip 2>/dev/null || true
'

# Run dehydration script
kubectl exec -n "$NAMESPACE" test-dev-server -- sh -c "
export AWS_ACCESS_KEY_ID=\$S3_ACCESS_KEY_ID
export AWS_SECRET_ACCESS_KEY=\$S3_SECRET_ACCESS_KEY
export AWS_DEFAULT_REGION=us-east-1

cd /app
zip -r /tmp/project.zip . -x '*.git/*' -x '*node_modules/*'

aws s3 cp /tmp/project.zip s3://tesslate-projects/projects/$USER_ID/$PROJECT_ID/latest.zip \
    --endpoint-url=http://minio.minio-system.svc.cluster.local:9000

echo 'Dehydration complete!'
"

log_success "Project dehydrated to S3"

# =============================================================================
# Test 6: Verify S3 Upload
# =============================================================================

log_test "Verifying S3 upload..."

# Check file exists in MinIO
RESULT=$(kubectl exec -n minio-system "$MINIO_POD" -- \
    mc ls local/tesslate-projects/projects/$USER_ID/$PROJECT_ID/latest.zip 2>/dev/null || echo "NOT_FOUND")

if echo "$RESULT" | grep -q "latest.zip"; then
    log_success "Project archive found in S3"
else
    log_error "Project archive not found in S3"
    exit 1
fi

# =============================================================================
# Test 7: Delete Project Files (Simulate Pod Deletion)
# =============================================================================

log_test "Deleting project files (simulating pod deletion)..."

kubectl exec -n "$NAMESPACE" test-dev-server -- rm -rf /app/*
FILES=$(kubectl exec -n "$NAMESPACE" test-dev-server -- ls /app 2>/dev/null || echo "")
if [ -z "$FILES" ]; then
    log_success "Project files deleted"
else
    log_error "Failed to delete project files"
    exit 1
fi

# =============================================================================
# Test 8: Simulate Hydration (Download from S3)
# =============================================================================

log_test "Testing hydration (download from S3)..."

kubectl exec -n "$NAMESPACE" test-dev-server -- sh -c "
export AWS_ACCESS_KEY_ID=\$S3_ACCESS_KEY_ID
export AWS_SECRET_ACCESS_KEY=\$S3_SECRET_ACCESS_KEY
export AWS_DEFAULT_REGION=us-east-1

# Download from S3
aws s3 cp s3://tesslate-projects/projects/$USER_ID/$PROJECT_ID/latest.zip /tmp/project.zip \
    --endpoint-url=http://minio.minio-system.svc.cluster.local:9000

# Extract to /app
cd /app
unzip -o /tmp/project.zip

rm /tmp/project.zip
echo 'Hydration complete!'
"

log_success "Project hydrated from S3"

# =============================================================================
# Test 9: Verify Restored Files
# =============================================================================

log_test "Verifying restored files..."

# Check package.json
CONTENT=$(kubectl exec -n "$NAMESPACE" test-dev-server -- cat /app/package.json)
if echo "$CONTENT" | grep -q "test-project"; then
    log_success "package.json restored correctly"
else
    log_error "package.json content mismatch"
    exit 1
fi

# Check index.js
CONTENT=$(kubectl exec -n "$NAMESPACE" test-dev-server -- cat /app/index.js)
if echo "$CONTENT" | grep -q "S3 Sandwich"; then
    log_success "index.js restored correctly"
else
    log_error "index.js content mismatch"
    exit 1
fi

# Check src/app.js
CONTENT=$(kubectl exec -n "$NAMESPACE" test-dev-server -- cat /app/src/app.js)
if echo "$CONTENT" | grep -q "greet"; then
    log_success "src/app.js restored correctly"
else
    log_error "src/app.js content mismatch"
    exit 1
fi

# =============================================================================
# Cleanup
# =============================================================================

log_info "Cleaning up test resources..."
kubectl delete namespace "$NAMESPACE" --ignore-not-found=true &

# Delete from S3
kubectl exec -n minio-system "$MINIO_POD" -- \
    mc rm --recursive --force local/tesslate-projects/projects/$USER_ID/$PROJECT_ID 2>/dev/null || true

# =============================================================================
# Summary
# =============================================================================

echo ""
echo -e "${GREEN}=============================================${NC}"
echo -e "${GREEN}  All S3 Sandwich Tests Passed!${NC}"
echo -e "${GREEN}=============================================${NC}"
echo ""
echo "Tests completed:"
echo "  ✓ MinIO connectivity"
echo "  ✓ Namespace and PVC creation"
echo "  ✓ Pod creation"
echo "  ✓ File creation in project"
echo "  ✓ Dehydration (upload to S3)"
echo "  ✓ S3 upload verification"
echo "  ✓ File deletion (pod cleanup simulation)"
echo "  ✓ Hydration (download from S3)"
echo "  ✓ File restoration verification"
echo ""
