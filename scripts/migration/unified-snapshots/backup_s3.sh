#!/usr/bin/env bash
#
# Backup the entire btrfs-snapshots S3 bucket before unified-snapshots migration.
#
# Non-destructive: server-side copy of all prefixes (blobs, index, manifests,
# tombstones) to backups/feat-unified-snapshots/. The backups/ prefix itself
# is excluded to prevent recursion.
#
# Originals remain in place so the running cluster continues to function.
# The convert step overwrites manifests/ in place; rollback restores from backup.
#
# Usage:
#   # Dry run
#   ./backup_s3.sh --bucket BUCKET --dry-run
#
#   # Resolve bucket from k8s secret
#   ./backup_s3.sh --from-k8s-secret --context tesslate-beta-eks --dry-run
#
#   # Execute full backup
#   ./backup_s3.sh --bucket BUCKET
#
#   # Manifests-only (small, fast — for testing the convert step)
#   ./backup_s3.sh --bucket BUCKET --manifests-only
#
set -euo pipefail

BUCKET=""
CONTEXT="tesslate-beta-eks"
DRY_RUN=false
FROM_K8S=false
MANIFESTS_ONLY=false

usage() {
    echo "Usage: $0 [--bucket BUCKET | --from-k8s-secret] [--context CTX] [--dry-run] [--manifests-only]"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bucket)          BUCKET="$2"; shift 2 ;;
        --from-k8s-secret) FROM_K8S=true; shift ;;
        --context)         CONTEXT="$2"; shift 2 ;;
        --dry-run)         DRY_RUN=true; shift ;;
        --manifests-only)  MANIFESTS_ONLY=true; shift ;;
        -h|--help)         usage ;;
        *)                 echo "Unknown arg: $1"; usage ;;
    esac
done

if $FROM_K8S; then
    BUCKET=$(kubectl --context="$CONTEXT" get secret tesslate-btrfs-csi-config \
        -n kube-system -o jsonpath='{.data.STORAGE_BUCKET}' | base64 -d)
    echo "Resolved bucket: $BUCKET"
fi

if [[ -z "$BUCKET" ]]; then
    echo "ERROR: --bucket or --from-k8s-secret required"
    usage
fi

BACKUP_PREFIX="backups/feat-unified-snapshots"
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

echo "============================================================"
echo "Unified Snapshots Migration — S3 Backup (non-destructive)"
echo "Mode: $( $DRY_RUN && echo 'DRY RUN' || echo 'LIVE' )"
if $MANIFESTS_ONLY; then
    echo "Scope: manifests/ only"
else
    echo "Scope: FULL bucket (blobs + index + manifests + tombstones)"
fi
echo "Bucket: $BUCKET"
echo "Destination: s3://$BUCKET/$BACKUP_PREFIX/"
echo "Timestamp: $TIMESTAMP"
echo "============================================================"
echo ""

# ── Prefix stats ────────────────────────────────────────────────────────────
count_and_size() {
    aws s3api list-objects-v2 --bucket "$BUCKET" --prefix "$1" \
        --query "[length(Contents[]) || \`0\`, sum(Contents[].Size) || \`0\`]" \
        --output text 2>/dev/null || echo "0	0"
}

echo "Source inventory:"
if $MANIFESTS_ONLY; then
    PREFIXES=(manifests)
else
    PREFIXES=(blobs index manifests tombstones)
fi

TOTAL_OBJ=0
TOTAL_BYTES=0
for p in "${PREFIXES[@]}"; do
    read -r C B <<< "$(count_and_size "$p/")"
    printf "  %-12s %8s objects  %15s bytes\n" "$p/" "$C" "$B"
    TOTAL_OBJ=$((TOTAL_OBJ + C))
    TOTAL_BYTES=$((TOTAL_BYTES + B))
done
printf "  %-12s %8s objects  %15s bytes\n" "TOTAL" "$TOTAL_OBJ" "$TOTAL_BYTES"
echo ""

if [[ "$TOTAL_OBJ" == "0" ]]; then
    echo "Nothing to backup."
    exit 0
fi

# ── Check existing backup ───────────────────────────────────────────────────
EXISTING=$(aws s3api list-objects-v2 --bucket "$BUCKET" --prefix "$BACKUP_PREFIX/" \
    --query "length(Contents[]) || \`0\`" --output text 2>/dev/null || echo "0")

if [[ "$EXISTING" != "0" ]]; then
    echo "WARNING: Backup path already contains $EXISTING object(s):"
    echo "  s3://$BUCKET/$BACKUP_PREFIX/"
    if ! $DRY_RUN; then
        echo ""
        echo "Aborting for safety. To overwrite, clear first:"
        echo "  aws s3 rm s3://$BUCKET/$BACKUP_PREFIX/ --recursive"
        exit 1
    fi
fi

# ── Dry run ──────────────────────────────────────────────────────────────────
if $DRY_RUN; then
    echo "DRY RUN — would server-side copy $TOTAL_OBJ objects ($TOTAL_BYTES bytes)"
    echo ""
    if $MANIFESTS_ONLY; then
        echo "Command equivalent:"
        echo "  aws s3 cp s3://$BUCKET/manifests/ s3://$BUCKET/$BACKUP_PREFIX/manifests/ --recursive"
    else
        echo "Command equivalent:"
        echo "  aws s3 cp s3://$BUCKET/ s3://$BUCKET/$BACKUP_PREFIX/ --recursive --exclude 'backups/*'"
    fi
    echo ""
    echo "To execute, run without --dry-run"
    exit 0
fi

# ── Execute backup ───────────────────────────────────────────────────────────
# Bump concurrency for the large blob dataset.
aws configure set default.s3.max_concurrent_requests 20 2>/dev/null || true

echo "Step 1: Server-side copy (may take a while for large datasets)..."
if $MANIFESTS_ONLY; then
    aws s3 cp "s3://$BUCKET/manifests/" "s3://$BUCKET/$BACKUP_PREFIX/manifests/" \
        --recursive --only-show-errors
else
    aws s3 cp "s3://$BUCKET/" "s3://$BUCKET/$BACKUP_PREFIX/" \
        --recursive --exclude "backups/*" --only-show-errors
fi
echo "  Copy pass complete."

# ── Catch-up sync for any objects that changed mid-copy ──────────────────────
echo ""
echo "Step 2: Sync to catch any mid-copy changes..."
if $MANIFESTS_ONLY; then
    aws s3 sync "s3://$BUCKET/manifests/" "s3://$BUCKET/$BACKUP_PREFIX/manifests/" \
        --only-show-errors
else
    aws s3 sync "s3://$BUCKET/" "s3://$BUCKET/$BACKUP_PREFIX/" \
        --exclude "backups/*" --only-show-errors
fi
echo "  Sync complete."

# ── Verify per-prefix counts ────────────────────────────────────────────────
echo ""
echo "Step 3: Verify per-prefix counts"
FAILED=0
for p in "${PREFIXES[@]}"; do
    read -r SRC_C _ <<< "$(count_and_size "$p/")"
    read -r BAK_C _ <<< "$(count_and_size "$BACKUP_PREFIX/$p/")"
    if [[ "$SRC_C" == "$BAK_C" ]]; then
        printf "  %-12s %8s source = %8s backup  ✓\n" "$p/" "$SRC_C" "$BAK_C"
    else
        printf "  %-12s %8s source ≠ %8s backup  ✗\n" "$p/" "$SRC_C" "$BAK_C"
        FAILED=1
    fi
done

if [[ "$FAILED" == "1" ]]; then
    echo ""
    echo "ERROR: count mismatch. Re-run the script or investigate before proceeding."
    exit 1
fi

# ── Write marker ────────────────────────────────────────────────────────────
echo ""
echo "Step 4: Write backup marker"
MARKER=$(cat <<EOF
{
  "feature_branch": "feat/unified-snapshots-system",
  "backup_completed_at": "$TIMESTAMP",
  "scope": "$( $MANIFESTS_ONLY && echo 'manifests-only' || echo 'full bucket' )",
  "excluded": ["backups/"],
  "total_objects": $TOTAL_OBJ,
  "total_size_bytes": $TOTAL_BYTES,
  "purpose": "Pre-migration backup before DAG manifest conversion. Blobs/index/tombstones are format-identical on the feature branch; only manifests will be transformed."
}
EOF
)
echo "$MARKER" | aws s3 cp - "s3://$BUCKET/$BACKUP_PREFIX/BACKUP_INFO.json" \
    --content-type application/json --quiet
echo "  Marker at s3://$BUCKET/$BACKUP_PREFIX/BACKUP_INFO.json"

echo ""
echo "============================================================"
echo "Backup complete. Originals preserved — cluster can keep running."
echo "  Source:      s3://$BUCKET/              ($TOTAL_OBJ objects)"
echo "  Destination: s3://$BUCKET/$BACKUP_PREFIX/"
echo ""
echo "Rollback: ./rollback.sh --bucket $BUCKET"
echo "============================================================"
