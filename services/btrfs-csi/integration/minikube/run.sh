#!/bin/bash
# run.sh - Master script for btrfs CSI minikube integration tests.
#
# Runs the full lifecycle: setup -> test -> teardown.
#
# Usage:
#   ./run.sh              # Run tests, keep cluster for debugging on failure
#   ./run.sh --cleanup    # Run tests, delete cluster when done (CI mode)
#
# Exit code: 0 if all tests pass, 1 on any failure.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLEANUP="${1:-}"
TEST_EXIT=0

echo "============================================="
echo " Tesslate btrfs CSI - Integration Test Suite"
echo "============================================="
echo "Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo ""

# -------------------------------------------------------------------
# Phase 1: Setup
# -------------------------------------------------------------------
echo ">>>>> PHASE 1: SETUP <<<<<"
echo ""
if ! "$SCRIPT_DIR/setup.sh"; then
    echo ""
    echo "SETUP FAILED - aborting tests."
    echo "Check the output above for errors."
    echo "To clean up: $SCRIPT_DIR/teardown.sh --delete"
    exit 1
fi
echo ""

# -------------------------------------------------------------------
# Phase 2: Run tests
# -------------------------------------------------------------------
echo ">>>>> PHASE 2a: PVC LIFECYCLE TESTS <<<<<"
echo ""
if "$SCRIPT_DIR/test-pvc-lifecycle.sh"; then
    echo ""
    echo "PVC lifecycle tests passed."
else
    TEST_EXIT=$?
    echo ""
    echo "PVC lifecycle tests FAILED (exit code: $TEST_EXIT)."
    echo ""

    # Dump diagnostic info on failure
    echo "--- Diagnostic info ---"
    PROFILE="tesslate-csi-test"
    KUBECTL="kubectl --context=${PROFILE}"

    echo ""
    echo "CSI controller logs:"
    $KUBECTL logs -n kube-system deployment/tesslate-volume-hub -c hub --tail=50 2>/dev/null || echo "(no logs)"

    echo ""
    echo "CSI node logs:"
    $KUBECTL logs -n kube-system daemonset/tesslate-btrfs-csi-node -c tesslate-btrfs-csi --tail=50 2>/dev/null || echo "(no logs)"

    echo ""
    echo "Pods in csi-test namespace:"
    $KUBECTL get pods -n csi-test -o wide 2>/dev/null || echo "(namespace not found)"

    echo ""
    echo "PVCs in csi-test namespace:"
    $KUBECTL get pvc -n csi-test 2>/dev/null || echo "(namespace not found)"

    echo ""
    echo "VolumeSnapshots in csi-test namespace:"
    $KUBECTL get volumesnapshot -n csi-test 2>/dev/null || echo "(namespace not found)"

    echo ""
    echo "Events in csi-test namespace:"
    $KUBECTL get events -n csi-test --sort-by=.lastTimestamp 2>/dev/null | tail -20 || echo "(namespace not found)"
fi
echo ""

# -------------------------------------------------------------------
# Phase 2b: Template lifecycle tests
# -------------------------------------------------------------------
echo ">>>>> PHASE 2b: TEMPLATE LIFECYCLE TESTS <<<<<"
echo ""
if [ "$TEST_EXIT" -eq 0 ]; then
    if "$SCRIPT_DIR/test-template-lifecycle.sh"; then
        echo ""
        echo "Template lifecycle tests passed."
    else
        TEST_EXIT=$?
        echo ""
        echo "Template lifecycle tests FAILED (exit code: $TEST_EXIT)."
        echo ""

        # Dump diagnostic info on failure
        PROFILE="tesslate-csi-test"
        KUBECTL="kubectl --context=${PROFILE}"

        echo "--- Diagnostic info ---"
        echo ""
        echo "CSI controller logs:"
        $KUBECTL logs -n kube-system deployment/tesslate-volume-hub -c hub --tail=50 2>/dev/null || echo "(no logs)"

        echo ""
        echo "Pods in csi-template-test namespace:"
        $KUBECTL get pods -n csi-template-test -o wide 2>/dev/null || echo "(namespace not found)"

        echo ""
        echo "PVCs in csi-template-test namespace:"
        $KUBECTL get pvc -n csi-template-test 2>/dev/null || echo "(namespace not found)"

        echo ""
        echo "Events in csi-template-test namespace:"
        $KUBECTL get events -n csi-template-test --sort-by=.lastTimestamp 2>/dev/null | tail -20 || echo "(namespace not found)"
    fi
else
    echo "Skipping template tests (PVC lifecycle tests failed)."
fi
echo ""

# -------------------------------------------------------------------
# Phase 3: Teardown
# -------------------------------------------------------------------
echo ">>>>> PHASE 3: TEARDOWN <<<<<"
echo ""
if [ "$CLEANUP" = "--cleanup" ]; then
    "$SCRIPT_DIR/teardown.sh" --delete
else
    "$SCRIPT_DIR/teardown.sh"
    if [ "$TEST_EXIT" -ne 0 ]; then
        echo ""
        echo "Cluster kept running for debugging. To delete:"
        echo "  $SCRIPT_DIR/teardown.sh --delete"
    fi
fi
echo ""

exit "$TEST_EXIT"
