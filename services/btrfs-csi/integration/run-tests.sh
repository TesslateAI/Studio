#!/bin/bash
set -euo pipefail

POOL_DIR="/mnt/tesslate-pool"
LOOP_FILE="/tmp/btrfs-test.img"
LOOP_SIZE="${BTRFS_POOL_SIZE:-1G}"

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
btrfs subvolume create "$POOL_DIR/layers"

# Enable quotas for capacity tracking (non-fatal — may fail in some container runtimes)
btrfs quota enable "$POOL_DIR" 2>/dev/null || echo "WARNING: quotas not available (non-fatal)"

echo "=== btrfs pool ready at $POOL_DIR ==="
btrfs filesystem usage "$POOL_DIR"
echo ""

# --- Start MinIO for S3 integration tests ---
echo "=== Starting MinIO (S3-compatible storage) ==="
MINIO_ROOT_USER=minioadmin MINIO_ROOT_PASSWORD=minioadmin \
    minio server /tmp/minio-data --address ":9000" --console-address ":9001" --quiet &
MINIO_PID=$!

# Wait for MinIO to be ready (up to 10 seconds).
for i in $(seq 1 20); do
    if wget -q --spider http://localhost:9000/minio/health/live 2>/dev/null; then
        echo "MinIO ready"
        break
    fi
    sleep 0.5
done

export TESSLATE_S3_ENDPOINT="localhost:9000"

# Run integration tests
echo "=== Running integration tests ==="
cd /build
TEST_TAGS="integration"
if [ -n "${EXTRA_TEST_TAGS:-}" ]; then
    TEST_TAGS="integration,$EXTRA_TEST_TAGS"
fi
TEST_TIMEOUT="${TEST_TIMEOUT:-300s}"
TESSLATE_BTRFS_POOL="$POOL_DIR" TESSLATE_S3_ENDPOINT="$TESSLATE_S3_ENDPOINT" go test -v -tags="$TEST_TAGS" -count=1 ./integration/... -timeout "$TEST_TIMEOUT"
EXIT_CODE=$?

# Cleanup
echo ""
echo "=== Cleanup ==="
# Kill MinIO
if [ -n "$MINIO_PID" ]; then
    kill $MINIO_PID 2>/dev/null || true
fi
umount "$POOL_DIR" 2>/dev/null || true
rm -f "$LOOP_FILE"

exit $EXIT_CODE
