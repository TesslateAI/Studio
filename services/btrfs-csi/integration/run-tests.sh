#!/bin/bash
set -euo pipefail

POOL_DIR="/mnt/tesslate-pool"
LOOP_FILE="/tmp/btrfs-test.img"
LOOP_SIZE="512M"

echo "=== Setting up btrfs loopback filesystem ==="

# Create a loopback file and format as btrfs
truncate -s "$LOOP_SIZE" "$LOOP_FILE"
mkfs.btrfs -f -q "$LOOP_FILE"

# Mount it
mkdir -p "$POOL_DIR"
mount -o loop "$LOOP_FILE" "$POOL_DIR"

# Create pool structure
btrfs subvolume create "$POOL_DIR/templates"
btrfs subvolume create "$POOL_DIR/volumes"
btrfs subvolume create "$POOL_DIR/snapshots"

# Enable quotas for capacity tracking (non-fatal — may fail in some container runtimes)
btrfs quota enable "$POOL_DIR" 2>/dev/null || echo "WARNING: quotas not available (non-fatal)"

echo "=== btrfs pool ready at $POOL_DIR ==="
btrfs filesystem usage "$POOL_DIR"
echo ""

# Run integration tests
echo "=== Running integration tests ==="
cd /build
TESSLATE_BTRFS_POOL="$POOL_DIR" go test -v -tags=integration -count=1 ./integration/... -timeout 120s
EXIT_CODE=$?

# Cleanup
echo ""
echo "=== Cleanup ==="
umount "$POOL_DIR" 2>/dev/null || true
rm -f "$LOOP_FILE"

exit $EXIT_CODE
