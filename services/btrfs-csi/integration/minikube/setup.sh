#!/bin/bash
# setup.sh - Provision minikube cluster, btrfs loopback filesystem, and deploy the CSI driver.
#
# This script is idempotent: re-running it will skip steps that are already done.
# Requires: minikube, docker, kubectl
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSI_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROFILE="tesslate-csi-test"
KUBECTL="kubectl --context=${PROFILE}"

echo "============================================="
echo " Tesslate btrfs CSI - Minikube Setup"
echo "============================================="
echo "CSI root: $CSI_ROOT"
echo "Minikube profile: $PROFILE"
echo ""

# -------------------------------------------------------------------
# 1. Ensure minikube cluster is running
# -------------------------------------------------------------------
echo "--- Step 1: Minikube cluster ---"
if minikube -p "$PROFILE" status --format='{{.Host}}' 2>/dev/null | grep -q "Running"; then
    echo "Minikube profile '$PROFILE' is already running."
else
    echo "Starting minikube profile '$PROFILE'..."
    minikube start -p "$PROFILE" \
        --driver=docker \
        --memory=4096 \
        --cpus=2 \
        --wait=all
fi
echo ""

# -------------------------------------------------------------------
# 2. Set up btrfs loopback filesystem inside the minikube VM
# -------------------------------------------------------------------
echo "--- Step 2: btrfs loopback filesystem ---"

# The minikube Docker-driver node runs a Linux VM. We SSH in to set up btrfs.
# Minikube base images vary (Alpine vs Debian), so we try both package managers.
minikube -p "$PROFILE" ssh -- "
    # Ensure sbin paths are available (mkfs.btrfs lives in /usr/sbin)
    export PATH=\"\$PATH:/usr/sbin:/sbin\"

    # Skip if already mounted
    if mountpoint -q /mnt/tesslate-pool 2>/dev/null; then
        echo 'btrfs pool already mounted at /mnt/tesslate-pool'
        exit 0
    fi

    echo 'Installing btrfs-progs...'
    # Try Alpine (apk) first, then Debian/Ubuntu (apt-get)
    if command -v apk >/dev/null 2>&1; then
        sudo apk add --no-cache btrfs-progs || true
    elif command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update -qq && sudo apt-get install -y -qq btrfs-progs || true
    elif command -v tdnf >/dev/null 2>&1; then
        sudo tdnf install -y btrfs-progs || true
    else
        echo 'WARNING: Unknown package manager, assuming btrfs-progs is available'
    fi

    # Verify btrfs tools are present (check sbin paths too)
    export PATH=\"\$PATH:/usr/sbin:/sbin\"
    if ! command -v mkfs.btrfs >/dev/null 2>&1; then
        echo 'ERROR: mkfs.btrfs not found after install attempt'
        exit 1
    fi

    echo 'Creating btrfs loopback image (1G)...'
    sudo truncate -s 1G /tmp/btrfs-test.img
    sudo mkfs.btrfs -f /tmp/btrfs-test.img

    echo 'Mounting btrfs filesystem...'
    sudo mkdir -p /mnt/tesslate-pool
    sudo mount -o loop /tmp/btrfs-test.img /mnt/tesslate-pool

    echo 'Creating pool subvolumes...'
    sudo btrfs subvolume create /mnt/tesslate-pool/templates
    sudo btrfs subvolume create /mnt/tesslate-pool/volumes
    sudo btrfs subvolume create /mnt/tesslate-pool/snapshots

    # Enable quotas (non-fatal if unsupported in this environment)
    sudo btrfs quota enable /mnt/tesslate-pool 2>/dev/null || echo 'WARNING: quotas not available (non-fatal)'

    echo 'btrfs pool ready:'
    sudo btrfs filesystem usage /mnt/tesslate-pool
"
echo ""

# -------------------------------------------------------------------
# 3. Build CSI driver image
# -------------------------------------------------------------------
echo "--- Step 3: Build CSI driver image ---"
echo "Building tesslate-btrfs-csi:test from $CSI_ROOT ..."
docker build -t tesslate-btrfs-csi:test -f "$CSI_ROOT/Dockerfile" "$CSI_ROOT"
echo ""

# -------------------------------------------------------------------
# 4. Load image into minikube
# -------------------------------------------------------------------
echo "--- Step 4: Load image into minikube ---"
# Delete old image first to ensure the new one is actually loaded
minikube -p "$PROFILE" ssh -- "docker rmi -f tesslate-btrfs-csi:test 2>/dev/null || true"
minikube -p "$PROFILE" image load tesslate-btrfs-csi:test
echo "Image loaded. Verifying..."
minikube -p "$PROFILE" ssh -- "docker images | grep tesslate-btrfs-csi"
echo ""

# -------------------------------------------------------------------
# 5. Install VolumeSnapshot CRDs (minikube does not include them)
# -------------------------------------------------------------------
echo "--- Step 5: Install VolumeSnapshot CRDs ---"

SNAPSHOTTER_VERSION="v8.2.0"
CRD_BASE="https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/${SNAPSHOTTER_VERSION}/client/config/crd"

# Apply CRDs (idempotent)
for crd in \
    "snapshot.storage.k8s.io_volumesnapshotclasses.yaml" \
    "snapshot.storage.k8s.io_volumesnapshotcontents.yaml" \
    "snapshot.storage.k8s.io_volumesnapshots.yaml"; do
    echo "  Applying CRD: $crd"
    $KUBECTL apply -f "${CRD_BASE}/${crd}" --server-side 2>/dev/null || \
    $KUBECTL apply -f "${CRD_BASE}/${crd}"
done

# Deploy the snapshot controller (required for VolumeSnapshot objects to reconcile)
CONTROLLER_BASE="https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/${SNAPSHOTTER_VERSION}/deploy/kubernetes/snapshot-controller"
echo "  Deploying snapshot controller..."
$KUBECTL apply -f "${CONTROLLER_BASE}/rbac-snapshot-controller.yaml" 2>/dev/null || true
$KUBECTL apply -f "${CONTROLLER_BASE}/setup-snapshot-controller.yaml" 2>/dev/null || true

echo ""

# -------------------------------------------------------------------
# 6. Deploy CSI driver via kustomize overlay
# -------------------------------------------------------------------
echo "--- Step 6: Deploy CSI driver ---"
$KUBECTL apply -k "$SCRIPT_DIR"

echo ""
echo "Waiting for CSI controller to be ready..."
$KUBECTL rollout status deployment/tesslate-btrfs-csi-controller -n kube-system --timeout=120s

echo "Waiting for CSI node DaemonSet to be ready..."
$KUBECTL rollout status daemonset/tesslate-btrfs-csi-node -n kube-system --timeout=120s

echo ""
echo "--- CSI driver pods ---"
$KUBECTL get pods -n kube-system -l 'app in (tesslate-btrfs-csi-controller,tesslate-btrfs-csi-node)' -o wide

echo ""
echo "============================================="
echo " Setup complete"
echo "============================================="
