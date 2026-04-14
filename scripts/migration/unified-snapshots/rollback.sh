#!/usr/bin/env bash
#
# Rollback unified-snapshots migration by restoring from backup.
#
# Restores the full bucket contents (blobs, index, manifests, tombstones) from
# backups/feat-unified-snapshots/ back to their canonical locations. Useful if
# the manifest conversion went wrong or the new images need to be rolled back.
#
# The backups/ prefix itself is left alone.
#
# Usage:
#   ./rollback.sh --dry-run
#   ./rollback.sh --bucket BUCKET
#   ./rollback.sh --from-k8s-secret --context tesslate-beta-eks
#   ./rollback.sh --bucket BUCKET --manifests-only   # only restore manifests/
#
set -euo pipefail

BUCKET=""
CONTEXT="tesslate-beta-eks"
DRY_RUN=false
FROM_K8S=false
MANIFESTS_ONLY=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bucket)          BUCKET="$2"; shift 2 ;;
        --from-k8s-secret) FROM_K8S=true; shift ;;
        --context)         CONTEXT="$2"; shift 2 ;;
        --dry-run)         DRY_RUN=true; shift ;;
        --manifests-only)  MANIFESTS_ONLY=true; shift ;;
        -h|--help)
            echo "Usage: $0 [--bucket BUCKET | --from-k8s-secret] [--context CTX] [--dry-run] [--manifests-only]"
            exit 0 ;;
        *)  echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if $FROM_K8S; then
    BUCKET=$(kubectl --context="$CONTEXT" get secret tesslate-btrfs-csi-config \
        -n kube-system -o jsonpath='{.data.STORAGE_BUCKET}' | base64 -d)
    echo "Resolved bucket: $BUCKET"
fi

if [[ -z "$BUCKET" ]]; then
    echo "ERROR: --bucket or --from-k8s-secret required"
    exit 1
fi

BACKUP_PREFIX="backups/feat-unified-snapshots"

echo "============================================================"
echo "Unified Snapshots Migration — ROLLBACK"
echo "Mode: $( $DRY_RUN && echo 'DRY RUN' || echo 'LIVE' )"
echo "Bucket: $BUCKET"
if $MANIFESTS_ONLY; then
    echo "Scope: manifests/ only"
else
    echo "Scope: FULL (blobs, index, manifests, tombstones)"
fi
echo "============================================================"
echo ""

count_and_size() {
    aws s3api list-objects-v2 --bucket "$BUCKET" --prefix "$1" \
        --query "[length(Contents[]) || \`0\`, sum(Contents[].Size) || \`0\`]" \
        --output text 2>/dev/null || echo "0	0"
}

if $MANIFESTS_ONLY; then
    PREFIXES=(manifests)
else
    PREFIXES=(blobs index manifests tombstones)
fi

# Verify backup exists
echo "Backup inventory:"
TOTAL_BAK=0
for p in "${PREFIXES[@]}"; do
    read -r C _ <<< "$(count_and_size "$BACKUP_PREFIX/$p/")"
    printf "  %-12s %8s objects\n" "$p/" "$C"
    TOTAL_BAK=$((TOTAL_BAK + C))
done
echo ""

if [[ "$TOTAL_BAK" == "0" ]]; then
    echo "ERROR: No backup found at s3://$BUCKET/$BACKUP_PREFIX/"
    exit 1
fi

if $DRY_RUN; then
    echo "[dry-run] Would restore:"
    for p in "${PREFIXES[@]}"; do
        echo "  s3://$BUCKET/$BACKUP_PREFIX/$p/ → s3://$BUCKET/$p/"
    done
    echo ""
    echo "To execute, run without --dry-run"
    exit 0
fi

aws configure set default.s3.max_concurrent_requests 20 2>/dev/null || true

# For manifests, fully replace (remove then sync). For large prefixes, sync
# handles updates in place without deleting unrelated objects.
for p in "${PREFIXES[@]}"; do
    echo "Restoring $p/..."
    if [[ "$p" == "manifests" ]]; then
        # Full replace for manifests — the converter may have written new keys
        aws s3 rm "s3://$BUCKET/$p/" --recursive --only-show-errors
    fi
    aws s3 sync "s3://$BUCKET/$BACKUP_PREFIX/$p/" "s3://$BUCKET/$p/" \
        --only-show-errors
done

echo ""
echo "Step: Verify restored counts"
FAILED=0
for p in "${PREFIXES[@]}"; do
    read -r SRC_C _ <<< "$(count_and_size "$p/")"
    read -r BAK_C _ <<< "$(count_and_size "$BACKUP_PREFIX/$p/")"
    if [[ "$SRC_C" == "$BAK_C" ]]; then
        printf "  %-12s %8s restored = %8s backup  ✓\n" "$p/" "$SRC_C" "$BAK_C"
    else
        printf "  %-12s %8s restored ≠ %8s backup  ✗\n" "$p/" "$SRC_C" "$BAK_C"
        FAILED=1
    fi
done

if [[ "$FAILED" == "1" ]]; then
    echo ""
    echo "ERROR: count mismatch after restore."
    exit 1
fi

echo ""
echo "============================================================"
echo "Rollback complete. Next: redeploy develop-branch images."
echo "============================================================"
