#!/bin/bash
# teardown.sh - Clean up test resources and optionally delete the minikube cluster.
#
# Usage:
#   ./teardown.sh           # Clean test namespace only (keep cluster for re-runs)
#   ./teardown.sh --delete  # Also delete the minikube profile entirely
set -euo pipefail

PROFILE="tesslate-csi-test"
KUBECTL="kubectl --context=${PROFILE}"
NS="csi-test"

echo "============================================="
echo " Tesslate btrfs CSI - Teardown"
echo "============================================="
echo ""

# -------------------------------------------------------------------
# 1. Delete test namespace and all its resources
# -------------------------------------------------------------------
echo "--- Deleting test namespaces ---"
$KUBECTL delete namespace "$NS" --ignore-not-found --wait=true --timeout=60s 2>/dev/null || true
$KUBECTL delete namespace "csi-template-test" --ignore-not-found --wait=true --timeout=60s 2>/dev/null || true
echo "Test namespaces cleaned up."
echo ""

# -------------------------------------------------------------------
# 1b. Clean up template test StorageClass (cluster-scoped)
# -------------------------------------------------------------------
echo "--- Cleaning up template test StorageClass ---"
$KUBECTL delete storageclass tesslate-btrfs-test-tmpl --ignore-not-found 2>/dev/null || true
echo ""

# -------------------------------------------------------------------
# 2. Clean up VolumeSnapshotContents (cluster-scoped, not in namespace)
# -------------------------------------------------------------------
echo "--- Cleaning up VolumeSnapshotContents ---"
# Delete any snapshot contents created by our test
SNAP_CONTENTS=$($KUBECTL get volumesnapshotcontent -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)
if [ -n "$SNAP_CONTENTS" ]; then
    echo "$SNAP_CONTENTS" | while read -r name; do
        if [ -n "$name" ]; then
            echo "  Deleting VolumeSnapshotContent: $name"
            $KUBECTL delete volumesnapshotcontent "$name" --ignore-not-found 2>/dev/null || true
        fi
    done
fi
echo ""

# -------------------------------------------------------------------
# 3. Optionally delete the minikube profile
# -------------------------------------------------------------------
if [ "${1:-}" = "--delete" ]; then
    echo "--- Deleting minikube profile '$PROFILE' ---"
    minikube -p "$PROFILE" delete
    echo "Minikube profile deleted."
else
    echo "Minikube profile '$PROFILE' kept running (pass --delete to remove it)."
    echo "To re-run tests:  ./test-pvc-lifecycle.sh"
    echo "To delete cluster: ./teardown.sh --delete"
fi

echo ""
echo "============================================="
echo " Teardown complete"
echo "============================================="
