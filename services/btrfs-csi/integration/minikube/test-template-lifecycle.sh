#!/bin/bash
# test-template-lifecycle.sh - End-to-end template volume lifecycle test.
#
# Tests the PromoteToTemplate → template StorageClass → PVC creation flow:
#   1. Create a PVC (simulates a builder job's build volume)
#   2. Populate it with files via a pod (simulates git clone + npm install)
#   3. Get the CSI volume ID from the bound PV
#   4. Promote the volume to a template (via kubectl exec into CSI pod)
#   5. Create a StorageClass referencing the template
#   6. Create a new PVC from the template StorageClass
#   7. Mount the new PVC and verify template files are present
#   8. Cleanup
#
# Requires: setup.sh has been run successfully
set -euo pipefail

PROFILE="tesslate-csi-test"
KUBECTL="kubectl --context=${PROFILE}"
NS="csi-template-test"

PASS_COUNT=0
FAIL_COUNT=0

pass() {
    PASS_COUNT=$((PASS_COUNT + 1))
    echo "PASS: $1"
}

fail() {
    FAIL_COUNT=$((FAIL_COUNT + 1))
    echo "FAIL: $1"
    exit 1
}

cleanup_namespace() {
    echo "Cleaning up test namespace '$NS'..."
    $KUBECTL delete namespace "$NS" --ignore-not-found --wait=false 2>/dev/null || true
    for i in $(seq 1 30); do
        if ! $KUBECTL get namespace "$NS" >/dev/null 2>&1; then
            break
        fi
        sleep 2
    done
}

cleanup_storageclass() {
    $KUBECTL delete storageclass tesslate-btrfs-test-tmpl --ignore-not-found 2>/dev/null || true
}

echo "============================================="
echo " Tesslate btrfs CSI - Template Lifecycle Test"
echo "============================================="
echo "Minikube profile: $PROFILE"
echo "Test namespace: $NS"
echo ""

# Pre-flight: verify CSI driver pods are running
echo "--- Pre-flight check ---"
CONTROLLER_READY=$($KUBECTL get deployment tesslate-btrfs-csi-controller -n kube-system -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
NODE_READY=$($KUBECTL get daemonset tesslate-btrfs-csi-node -n kube-system -o jsonpath='{.status.numberReady}' 2>/dev/null || echo "0")

if [ "$CONTROLLER_READY" = "0" ] || [ "$NODE_READY" = "0" ]; then
    echo "CSI driver not ready (controller=$CONTROLLER_READY, node=$NODE_READY)"
    echo "Run setup.sh first."
    exit 1
fi
echo "CSI driver ready (controller=$CONTROLLER_READY, node=$NODE_READY)"
echo ""

# Clean up any leftover test resources
cleanup_namespace
cleanup_storageclass

# Find CSI controller pod (used for kubectl exec later)
CSI_POD=$($KUBECTL get pod -n kube-system -l app=tesslate-btrfs-csi-controller -o jsonpath='{.items[0].metadata.name}')
echo "CSI controller pod: $CSI_POD"
echo ""

# ===================================================================
echo "=== Test 1: Create namespace and build PVC ==="
# ===================================================================
$KUBECTL create namespace "$NS"

cat <<'YAML' | $KUBECTL apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: template-build-vol
  namespace: csi-template-test
spec:
  storageClassName: tesslate-btrfs
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi
YAML

pass "Build PVC created with tesslate-btrfs StorageClass"
echo ""

# ===================================================================
echo "=== Test 2: Populate build volume (simulates builder job) ==="
# ===================================================================
cat <<'YAML' | $KUBECTL apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: template-builder
  namespace: csi-template-test
spec:
  containers:
  - name: builder
    image: alpine:3.20
    command:
    - sh
    - -c
    - |
      mkdir -p /workspace/src /workspace/node_modules/.cache
      echo '{"name": "test-nextjs-app", "version": "1.0.0"}' > /workspace/package.json
      echo 'console.log("hello")' > /workspace/src/index.js
      echo 'node_modules/' > /workspace/.gitignore
      echo '{}' > /workspace/node_modules/.package-lock.json
      echo 'TEMPLATE_BUILD_COMPLETE'
      sleep 3600
    volumeMounts:
    - name: data
      mountPath: /workspace
  volumes:
  - name: data
    persistentVolumeClaim:
      claimName: template-build-vol
YAML

echo "Waiting for builder pod to become Ready..."
$KUBECTL wait --for=condition=Ready pod/template-builder -n "$NS" --timeout=120s

# Verify files were written
CONTENT=$($KUBECTL exec -n "$NS" template-builder -- cat /workspace/package.json)
if echo "$CONTENT" | grep -q "test-nextjs-app"; then
    pass "Build volume populated with template files"
else
    fail "Expected package.json with 'test-nextjs-app', got: $CONTENT"
fi
echo ""

# ===================================================================
echo "=== Test 3: Get CSI volume ID from bound PV ==="
# ===================================================================

# Wait for PVC to be Bound
echo "Waiting for PVC to bind..."
for i in $(seq 1 30); do
    PHASE=$($KUBECTL get pvc template-build-vol -n "$NS" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Pending")
    if [ "$PHASE" = "Bound" ]; then
        break
    fi
    sleep 2
done

if [ "$PHASE" != "Bound" ]; then
    fail "PVC never became Bound (phase=$PHASE)"
fi

PV_NAME=$($KUBECTL get pvc template-build-vol -n "$NS" -o jsonpath='{.spec.volumeName}')
VOL_ID=$($KUBECTL get pv "$PV_NAME" -o jsonpath='{.spec.csi.volumeHandle}')

if [ -z "$VOL_ID" ]; then
    fail "Could not determine CSI volume ID"
fi

echo "PV: $PV_NAME, CSI Volume ID: $VOL_ID"
pass "Retrieved CSI volume ID: $VOL_ID"
echo ""

# ===================================================================
echo "=== Test 4: Promote build volume to template ==="
# ===================================================================

# Stop the builder pod first so the volume isn't mounted
$KUBECTL delete pod template-builder -n "$NS" --grace-period=0 --force 2>/dev/null || true
echo "Waiting for builder pod to terminate..."
for i in $(seq 1 30); do
    if ! $KUBECTL get pod template-builder -n "$NS" >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

# Delete the PVC to release the volume (CSI DeleteVolume won't run because
# we'll create the template snapshot before that). Actually, we need the volume
# to still exist. The PVC deletion triggers CSI DeleteVolume which would delete
# the subvolume. So we promote BEFORE deleting the PVC.

# Promote via kubectl exec into CSI pod - this simulates what PromoteToTemplate does:
# 1. Snapshot volumes/{volID} -> templates/{templateName} (read-only)
# 2. (In real flow, also uploads to S3 and deletes source - skipped in minikube)
TMPL_NAME="e2e-test-template"

echo "Promoting volume $VOL_ID to template $TMPL_NAME..."
$KUBECTL exec -n kube-system "$CSI_POD" -c tesslate-btrfs-csi -- sh -c "
    export PATH=\"\$PATH:/usr/sbin:/sbin\"

    VOL_PATH=\"/mnt/tesslate-pool/volumes/$VOL_ID\"
    TMPL_PATH=\"/mnt/tesslate-pool/templates/$TMPL_NAME\"

    # Remove existing template if present (refresh scenario)
    if [ -d \"\$TMPL_PATH\" ]; then
        btrfs subvolume delete \"\$TMPL_PATH\"
    fi

    # Create read-only snapshot (this is what PromoteToTemplate does)
    btrfs subvolume snapshot -r \"\$VOL_PATH\" \"\$TMPL_PATH\"

    # Verify template exists
    btrfs subvolume show \"\$TMPL_PATH\" >/dev/null 2>&1 && echo 'PROMOTE_OK'
"

# Verify it worked
PROMOTE_RESULT=$($KUBECTL exec -n kube-system "$CSI_POD" -c tesslate-btrfs-csi -- sh -c "
    [ -f /mnt/tesslate-pool/templates/$TMPL_NAME/package.json ] && echo 'FILES_OK' || echo 'FILES_MISSING'
")

if [ "$PROMOTE_RESULT" = "FILES_OK" ]; then
    pass "Volume promoted to template with files intact"
else
    fail "Template files missing after promotion"
fi
echo ""

# Now we can delete the build PVC (cleanup)
$KUBECTL delete pvc template-build-vol -n "$NS" --wait=false 2>/dev/null || true

# ===================================================================
echo "=== Test 5: Create template StorageClass ==="
# ===================================================================
cat <<YAML | $KUBECTL apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: tesslate-btrfs-test-tmpl
provisioner: btrfs.csi.tesslate.io
parameters:
  template: "$TMPL_NAME"
reclaimPolicy: Delete
volumeBindingMode: Immediate
allowVolumeExpansion: true
YAML

pass "Template StorageClass 'tesslate-btrfs-test-tmpl' created"
echo ""

# ===================================================================
echo "=== Test 6: Create PVC from template StorageClass ==="
# ===================================================================
cat <<'YAML' | $KUBECTL apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: project-from-template
  namespace: csi-template-test
spec:
  storageClassName: tesslate-btrfs-test-tmpl
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi
YAML

# Wait for PVC to bind
echo "Waiting for template PVC to bind..."
for i in $(seq 1 30); do
    PHASE=$($KUBECTL get pvc project-from-template -n "$NS" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Pending")
    if [ "$PHASE" = "Bound" ]; then
        break
    fi
    sleep 2
done

if [ "$PHASE" != "Bound" ]; then
    echo "--- PVC details ---"
    $KUBECTL describe pvc project-from-template -n "$NS" || true
    echo "--- CSI controller logs ---"
    $KUBECTL logs -n kube-system "$CSI_POD" -c tesslate-btrfs-csi --tail=30 || true
    fail "Template PVC never became Bound (phase=$PHASE)"
fi

pass "PVC 'project-from-template' created from template and Bound"
echo ""

# ===================================================================
echo "=== Test 7: Verify template content in new volume ==="
# ===================================================================
cat <<'YAML' | $KUBECTL apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: project-reader
  namespace: csi-template-test
spec:
  containers:
  - name: reader
    image: alpine:3.20
    command: ["sh", "-c", "cat /workspace/package.json && ls -la /workspace/ && sleep 3600"]
    volumeMounts:
    - name: data
      mountPath: /workspace
  volumes:
  - name: data
    persistentVolumeClaim:
      claimName: project-from-template
YAML

echo "Waiting for reader pod to become Ready..."
$KUBECTL wait --for=condition=Ready pod/project-reader -n "$NS" --timeout=120s

# Verify package.json content
PKG=$($KUBECTL exec -n "$NS" project-reader -- cat /workspace/package.json)
if echo "$PKG" | grep -q "test-nextjs-app"; then
    pass "Template content preserved: package.json has 'test-nextjs-app'"
else
    fail "Template content missing in new volume. Got: $PKG"
fi

# Verify directory structure
HAS_SRC=$($KUBECTL exec -n "$NS" project-reader -- sh -c "[ -d /workspace/src ] && echo 'yes' || echo 'no'")
if [ "$HAS_SRC" = "yes" ]; then
    pass "Template directory structure preserved: /workspace/src exists"
else
    fail "Template directory structure missing: /workspace/src not found"
fi

# Verify node_modules survived
HAS_MODULES=$($KUBECTL exec -n "$NS" project-reader -- sh -c "[ -f /workspace/node_modules/.package-lock.json ] && echo 'yes' || echo 'no'")
if [ "$HAS_MODULES" = "yes" ]; then
    pass "Template dependencies preserved: node_modules present"
else
    fail "Template dependencies missing: node_modules/.package-lock.json not found"
fi

# Verify the new volume is writable (not read-only like the template)
WRITE_OK=$($KUBECTL exec -n "$NS" project-reader -- sh -c "echo 'user-change' > /workspace/user-file.txt && cat /workspace/user-file.txt")
if [ "$WRITE_OK" = "user-change" ]; then
    pass "New volume is writable (not read-only)"
else
    fail "New volume appears to be read-only"
fi
echo ""

# ===================================================================
echo "=== Test 8: Cleanup ==="
# ===================================================================
# Delete test resources
$KUBECTL delete pod project-reader -n "$NS" --grace-period=0 --force 2>/dev/null || true
$KUBECTL delete pvc project-from-template -n "$NS" --wait=false 2>/dev/null || true
cleanup_storageclass

# Clean up template subvolume from the CSI pod
$KUBECTL exec -n kube-system "$CSI_POD" -c tesslate-btrfs-csi -- sh -c "
    export PATH=\"\$PATH:/usr/sbin:/sbin\"
    TMPL_PATH=\"/mnt/tesslate-pool/templates/$TMPL_NAME\"
    if [ -d \"\$TMPL_PATH\" ]; then
        btrfs subvolume delete \"\$TMPL_PATH\" 2>/dev/null || true
    fi
" 2>/dev/null || true

pass "Test resources cleaned up"
echo ""

# ===================================================================
echo "============================================="
echo " Results: $PASS_COUNT passed, $FAIL_COUNT failed"
echo "============================================="

if [ "$FAIL_COUNT" -gt 0 ]; then
    exit 1
fi

echo ""
echo "ALL TEMPLATE TESTS PASSED"
