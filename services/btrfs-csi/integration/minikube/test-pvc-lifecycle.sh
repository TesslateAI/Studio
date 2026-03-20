#!/bin/bash
# test-pvc-lifecycle.sh - End-to-end PVC lifecycle test for the btrfs CSI driver.
#
# Tests the full Kubernetes storage lifecycle:
#   1. Create PVC with tesslate-btrfs StorageClass
#   2. Mount PVC in a pod and write a file
#   3. Verify the file content
#   4. Create a VolumeSnapshot of the PVC
#   5. Delete the original pod and PVC
#   6. Restore a new PVC from the snapshot
#   7. Mount the restored PVC and verify the file survived
#
# Requires: setup.sh has been run successfully
set -euo pipefail

PROFILE="tesslate-csi-test"
KUBECTL="kubectl --context=${PROFILE}"
NS="csi-test"

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
    # Wait for namespace to actually disappear
    for i in $(seq 1 30); do
        if ! $KUBECTL get namespace "$NS" >/dev/null 2>&1; then
            break
        fi
        sleep 2
    done
}

echo "============================================="
echo " Tesslate btrfs CSI - PVC Lifecycle Test"
echo "============================================="
echo "Minikube profile: $PROFILE"
echo "Test namespace: $NS"
echo ""

# Pre-flight: verify CSI driver pods are running
echo "--- Pre-flight check ---"
CONTROLLER_READY=$($KUBECTL get deployment tesslate-volume-hub -n kube-system -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
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

# ===================================================================
echo "=== Test 1: Create namespace and PVC ==="
# ===================================================================
$KUBECTL create namespace "$NS"

cat <<'YAML' | $KUBECTL apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: test-vol
  namespace: csi-test
spec:
  storageClassName: tesslate-btrfs
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi
YAML

echo "PVC created."
pass "PVC test-vol created with tesslate-btrfs StorageClass"
echo ""

# ===================================================================
echo "=== Test 2: Create pod that mounts the PVC and writes a file ==="
# ===================================================================
cat <<'YAML' | $KUBECTL apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: test-writer
  namespace: csi-test
spec:
  containers:
  - name: writer
    image: alpine:3.20
    command: ["sh", "-c", "echo 'hello from btrfs csi' > /data/test.txt && echo 'WRITE_OK' && sleep 3600"]
    volumeMounts:
    - name: data
      mountPath: /data
  volumes:
  - name: data
    persistentVolumeClaim:
      claimName: test-vol
YAML

echo "Waiting for writer pod to become Ready..."
$KUBECTL wait --for=condition=Ready pod/test-writer -n "$NS" --timeout=120s
pass "Writer pod is Running and Ready"
echo ""

# ===================================================================
echo "=== Test 3: Verify file content ==="
# ===================================================================
CONTENT=$($KUBECTL exec -n "$NS" test-writer -- cat /data/test.txt)
if [ "$CONTENT" != "hello from btrfs csi" ]; then
    fail "Expected 'hello from btrfs csi', got '$CONTENT'"
fi
pass "File content verified: '$CONTENT'"
echo ""

# ===================================================================
echo "=== Test 4: Create VolumeSnapshot ==="
# ===================================================================
cat <<'YAML' | $KUBECTL apply -f -
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: test-snap
  namespace: csi-test
spec:
  volumeSnapshotClassName: tesslate-btrfs-snapshots
  source:
    persistentVolumeClaimName: test-vol
YAML

echo "Waiting for snapshot to become readyToUse..."
READY="false"
for i in $(seq 1 30); do
    READY=$($KUBECTL get volumesnapshot test-snap -n "$NS" -o jsonpath='{.status.readyToUse}' 2>/dev/null || echo "false")
    if [ "$READY" = "true" ]; then
        break
    fi
    sleep 2
done

if [ "$READY" != "true" ]; then
    echo "--- Snapshot details ---"
    $KUBECTL describe volumesnapshot test-snap -n "$NS" || true
    echo "--- VolumeSnapshotContent ---"
    $KUBECTL get volumesnapshotcontent -o yaml 2>/dev/null || true
    echo "--- CSI controller logs ---"
    $KUBECTL logs -n kube-system deployment/tesslate-volume-hub -c hub --tail=30 || true
    fail "Snapshot not readyToUse after 60s"
fi
pass "VolumeSnapshot 'test-snap' created and readyToUse=true"
echo ""

# ===================================================================
echo "=== Test 5: Delete original pod and PVC ==="
# ===================================================================
$KUBECTL delete pod test-writer -n "$NS" --grace-period=0 --force 2>/dev/null || true

# Wait for pod to fully terminate before deleting PVC
echo "Waiting for writer pod to terminate..."
for i in $(seq 1 30); do
    if ! $KUBECTL get pod test-writer -n "$NS" >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

$KUBECTL delete pvc test-vol -n "$NS"
echo "Waiting for PVC to be deleted..."
for i in $(seq 1 15); do
    if ! $KUBECTL get pvc test-vol -n "$NS" >/dev/null 2>&1; then
        break
    fi
    sleep 2
done
pass "Original pod and PVC deleted"
echo ""

# ===================================================================
echo "=== Test 6: Restore PVC from snapshot ==="
# ===================================================================
cat <<'YAML' | $KUBECTL apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: test-vol-restored
  namespace: csi-test
spec:
  storageClassName: tesslate-btrfs
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi
  dataSource:
    name: test-snap
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
YAML

pass "Restore PVC 'test-vol-restored' created from snapshot"
echo ""

# ===================================================================
echo "=== Test 7: Mount restored PVC and verify file ==="
# ===================================================================
cat <<'YAML' | $KUBECTL apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: test-reader
  namespace: csi-test
spec:
  containers:
  - name: reader
    image: alpine:3.20
    command: ["sh", "-c", "cat /data/test.txt && sleep 3600"]
    volumeMounts:
    - name: data
      mountPath: /data
  volumes:
  - name: data
    persistentVolumeClaim:
      claimName: test-vol-restored
YAML

echo "Waiting for reader pod to become Ready..."
$KUBECTL wait --for=condition=Ready pod/test-reader -n "$NS" --timeout=120s

RESTORED=$($KUBECTL exec -n "$NS" test-reader -- cat /data/test.txt)
if [ "$RESTORED" != "hello from btrfs csi" ]; then
    fail "Restored content = '$RESTORED', expected 'hello from btrfs csi'"
fi
pass "Restored PVC contains original file content: '$RESTORED'"
echo ""

# ===================================================================
echo "============================================="
echo " Results: $PASS_COUNT passed, $FAIL_COUNT failed"
echo "============================================="

if [ "$FAIL_COUNT" -gt 0 ]; then
    exit 1
fi

echo ""
echo "ALL TESTS PASSED"
