#!/usr/bin/env bash
#
# Full migration orchestrator for unified-snapshots on beta.
#
# Phases:
#   1. Stop cluster (scale deployments to 0, delete project namespaces)
#   2. Backup S3 manifests
#   3. Convert manifests to new DAG format
#   4. Deploy new images (rebuild + apply)
#   5. Start cluster
#
# Usage:
#   # Dry run — show what each phase would do without modifying anything
#   ./run_migration.sh --dry-run
#
#   # Execute migration
#   ./run_migration.sh
#
#   # Execute a single phase (for debugging/resuming)
#   ./run_migration.sh --phase stop
#   ./run_migration.sh --phase backup
#   ./run_migration.sh --phase convert
#   ./run_migration.sh --phase deploy
#   ./run_migration.sh --phase start
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

CONTEXT="tesslate-beta-eks"
NAMESPACE="tesslate"
DRY_RUN=false
PHASE=""

usage() {
    echo "Usage: $0 [--dry-run] [--phase stop|backup|convert|deploy|start] [--context CTX]"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)   DRY_RUN=true; shift ;;
        --phase)     PHASE="$2"; shift 2 ;;
        --context)   CONTEXT="$2"; shift 2 ;;
        -h|--help)   usage ;;
        *)           echo "Unknown arg: $1"; usage ;;
    esac
done

DRY_FLAG=""
if $DRY_RUN; then
    DRY_FLAG="--dry-run"
fi

TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)

echo "============================================================"
echo "Unified Snapshots Migration"
echo "Mode: $( $DRY_RUN && echo 'DRY RUN' || echo 'LIVE' )"
echo "Context: $CONTEXT"
echo "Phase: ${PHASE:-all}"
echo "Timestamp: $TIMESTAMP"
echo "============================================================"
echo ""

# --- Phase 1: Stop (full shutdown including storage plane) ---
phase_stop() {
    echo "====== Phase 1: Stop Cluster (full shutdown) ======"
    echo ""
    echo "This scales down EVERYTHING that can touch S3 manifests:"
    echo "  - App namespace ($NAMESPACE) deployments"
    echo "  - Project namespaces (proj-*)"
    echo "  - Volume Hub (kube-system)"
    echo "  - btrfs CSI DaemonSet (kube-system) — disabled via nodeSelector"
    echo ""

    # DaemonSets can't be scaled to 0 — patch nodeSelector to a non-matching label.
    local CSI_DS="tesslate-btrfs-csi-node"
    local CSI_DISABLE_PATCH='{"spec":{"template":{"spec":{"nodeSelector":{"tesslate.io/migration-disabled":"true"}}}}}'

    if $DRY_RUN; then
        echo "[dry-run] Would scale $NAMESPACE deployments to 0:"
        kubectl --context="$CONTEXT" -n "$NAMESPACE" get deploy -o name 2>/dev/null || true
        echo ""
        echo "[dry-run] Would delete project namespaces (proj-*):"
        kubectl --context="$CONTEXT" get ns -l tesslate.io/project -o name 2>/dev/null || echo "  (none found)"
        echo ""
        echo "[dry-run] Would scale kube-system/tesslate-volume-hub to 0"
        echo "[dry-run] Would patch kube-system/daemonset/$CSI_DS with disable nodeSelector"
        echo "  patch: $CSI_DISABLE_PATCH"
        return
    fi

    # 1. App namespace deployments
    echo "Step 1: Scaling $NAMESPACE deployments to 0..."
    kubectl --context="$CONTEXT" -n "$NAMESPACE" get deploy -o name | \
        xargs -r -I{} kubectl --context="$CONTEXT" -n "$NAMESPACE" scale {} --replicas=0
    echo "  Done."

    # 1b. Suspend CronJobs (prevent scheduled runs during migration)
    echo ""
    echo "Step 1b: Suspending CronJobs..."
    kubectl --context="$CONTEXT" -n "$NAMESPACE" get cronjobs -o name 2>/dev/null | \
        xargs -r -I{} kubectl --context="$CONTEXT" -n "$NAMESPACE" patch {} -p '{"spec":{"suspend":true}}'
    echo "  Done."

    # 2. Project namespaces
    echo ""
    echo "Step 2: Deleting project namespaces..."
    PROJECT_NS=$(kubectl --context="$CONTEXT" get ns -l tesslate.io/project -o name 2>/dev/null || true)
    if [[ -n "$PROJECT_NS" ]]; then
        echo "$PROJECT_NS" | xargs -I{} kubectl --context="$CONTEXT" delete {} --wait=false
        echo "  Deletion initiated for $(echo "$PROJECT_NS" | wc -l) namespace(s)."
    else
        echo "  No project namespaces found."
    fi

    # 3. Volume Hub
    echo ""
    echo "Step 3: Scaling Volume Hub to 0..."
    kubectl --context="$CONTEXT" -n kube-system scale deploy tesslate-volume-hub --replicas=0
    echo "  Done."

    # 4. btrfs CSI DaemonSet — disable via nodeSelector patch
    echo ""
    echo "Step 4: Disabling btrfs CSI DaemonSet via nodeSelector..."
    kubectl --context="$CONTEXT" -n kube-system patch daemonset "$CSI_DS" \
        --type=strategic --patch="$CSI_DISABLE_PATCH"
    echo "  Patched. Existing CSI pods will be evicted."

    # 5. Wait for everything to drain
    echo ""
    echo "Step 5: Waiting for pods to terminate..."
    kubectl --context="$CONTEXT" -n "$NAMESPACE" wait --for=delete pod --all --timeout=120s 2>/dev/null || true
    kubectl --context="$CONTEXT" -n kube-system wait --for=delete pod -l app=tesslate-volume-hub --timeout=120s 2>/dev/null || true
    kubectl --context="$CONTEXT" -n kube-system wait --for=delete pod -l app=tesslate-btrfs-csi-node --timeout=120s 2>/dev/null || true

    # 6. Verify nothing is still writing to S3 (ignore Completed/Succeeded CronJob pods)
    echo ""
    echo "Step 6: Verify shutdown"
    APP_PODS=$(kubectl --context="$CONTEXT" -n "$NAMESPACE" get pods \
        --field-selector=status.phase!=Succeeded --no-headers 2>/dev/null | wc -l)
    HUB_PODS=$(kubectl --context="$CONTEXT" -n kube-system get pods \
        -l app=tesslate-volume-hub --no-headers 2>/dev/null | wc -l)
    CSI_PODS=$(kubectl --context="$CONTEXT" -n kube-system get pods \
        -l app=tesslate-btrfs-csi-node --no-headers 2>/dev/null | wc -l)
    echo "  App namespace pods:  $APP_PODS (excl. Completed)"
    echo "  Volume Hub pods:     $HUB_PODS"
    echo "  CSI node pods:       $CSI_PODS"

    if [[ "$APP_PODS" != "0" || "$HUB_PODS" != "0" || "$CSI_PODS" != "0" ]]; then
        echo ""
        echo "WARNING: Some pods are still running. Wait and re-check before proceeding."
    else
        echo ""
        echo "Cluster fully stopped. Safe to proceed with backup/convert."
    fi
}

# --- Phase 2: Backup ---
phase_backup() {
    echo "====== Phase 2: Backup S3 Manifests ======"
    echo ""
    bash "$SCRIPT_DIR/backup_s3.sh" --from-k8s-secret --context "$CONTEXT" $DRY_FLAG
}

# --- Phase 3: Convert ---
phase_convert() {
    echo "====== Phase 3: Convert Manifests ======"
    echo ""

    # Resolve bucket for the converter
    BUCKET=$(kubectl --context="$CONTEXT" get secret tesslate-btrfs-csi-config \
        -n kube-system -o jsonpath='{.data.STORAGE_BUCKET}' | base64 -d)

    # Backup is non-destructive — manifests/ still contains the originals.
    # Converter reads each manifest, converts in place, writes back.
    if $DRY_RUN; then
        python3 "$SCRIPT_DIR/convert_manifests.py" --bucket "$BUCKET" --dry-run
    else
        python3 "$SCRIPT_DIR/convert_manifests.py" --bucket "$BUCKET"
    fi
}

# --- Phase 4: Deploy ---
phase_deploy() {
    echo "====== Phase 4: Deploy New Images ======"
    echo ""

    if $DRY_RUN; then
        echo "[dry-run] Would rebuild and push images to ECR (<AWS_ACCOUNT_ID>):"
        echo "  - tesslate-backend:beta"
        echo "  - tesslate-frontend:beta"
        echo "  - tesslate-btrfs-csi:beta"
        echo ""
        echo "[dry-run] Would apply kustomize overlays:"
        echo "  - k8s/overlays/aws-beta/"
        echo "  - services/btrfs-csi/deploy/"
        echo "  - k8s/base/volume-hub/"
        echo ""
        echo "[dry-run] Manifests that would be applied:"
        kubectl --context="$CONTEXT" apply -k "$REPO_ROOT/k8s/overlays/aws-beta/" --dry-run=client 2>&1 | head -20
        return
    fi

    echo "Building and pushing images..."
    echo "  (Run these manually or via your CI pipeline):"
    echo ""
    echo "  ./scripts/aws-deploy.sh build beta backend --cached"
    echo "  ./scripts/aws-deploy.sh build beta frontend --cached"
    echo "  ./scripts/aws-deploy.sh build beta btrfs-csi --cached"
    echo ""
    read -r -p "Press Enter after images are built and pushed (or Ctrl+C to abort)..."

    echo ""
    echo "Applying kustomize overlays..."
    kubectl --context="$CONTEXT" apply -k "$REPO_ROOT/services/btrfs-csi/deploy/"
    kubectl --context="$CONTEXT" apply -k "$REPO_ROOT/k8s/base/volume-hub/"
    kubectl --context="$CONTEXT" apply -k "$REPO_ROOT/k8s/overlays/aws-beta/"
    echo "  Applied."

    echo ""
    echo "Restarting CSI DaemonSet and Volume Hub to pick up new images..."
    kubectl --context="$CONTEXT" -n kube-system rollout restart daemonset/tesslate-btrfs-csi-node
    kubectl --context="$CONTEXT" -n kube-system rollout restart deploy/tesslate-volume-hub
    echo "  Rollout initiated."

    echo ""
    echo "Waiting for CSI and Hub to be ready..."
    kubectl --context="$CONTEXT" -n kube-system rollout status daemonset/tesslate-btrfs-csi-node --timeout=120s
    kubectl --context="$CONTEXT" -n kube-system rollout status deploy/tesslate-volume-hub --timeout=120s
    echo "  CSI and Hub ready."
}

# --- Phase 5: Start ---
phase_start() {
    echo "====== Phase 5: Start Cluster ======"
    echo ""
    echo "Bring-up order: storage plane first (CSI → Hub), then app plane."
    echo ""

    local CSI_DS="tesslate-btrfs-csi-node"

    if $DRY_RUN; then
        echo "[dry-run] Would remove disable nodeSelector from $CSI_DS"
        echo "[dry-run] Would scale tesslate-volume-hub to 1"
        echo "[dry-run] Would scale app deployments:"
        echo "  - litellm: 1, litellm-postgres: 1, postgres: 1, redis: 1"
        echo "  - tesslate-backend: 1, tesslate-frontend: 1, tesslate-worker: 1"
        return
    fi

    # 1. Re-enable CSI DaemonSet (remove disable nodeSelector)
    echo "Step 1: Re-enabling btrfs CSI DaemonSet..."
    kubectl --context="$CONTEXT" -n kube-system patch daemonset "$CSI_DS" \
        --type=json --patch='[{"op":"remove","path":"/spec/template/spec/nodeSelector/tesslate.io~1migration-disabled"}]' \
        2>/dev/null || echo "  (nodeSelector already removed)"
    kubectl --context="$CONTEXT" -n kube-system rollout status daemonset/"$CSI_DS" --timeout=180s
    echo "  CSI ready."

    # 2. Bring Volume Hub back
    echo ""
    echo "Step 2: Scaling Volume Hub to 1..."
    kubectl --context="$CONTEXT" -n kube-system scale deploy tesslate-volume-hub --replicas=1
    kubectl --context="$CONTEXT" -n kube-system rollout status deploy/tesslate-volume-hub --timeout=180s
    echo "  Hub ready."

    # 3. Stateful dependencies
    echo ""
    echo "Step 3: Scaling stateful dependencies..."
    for d in postgres redis litellm-postgres litellm; do
        if kubectl --context="$CONTEXT" -n "$NAMESPACE" get deploy "$d" >/dev/null 2>&1; then
            kubectl --context="$CONTEXT" -n "$NAMESPACE" scale deploy/"$d" --replicas=1
        fi
    done
    for d in postgres redis litellm-postgres litellm; do
        if kubectl --context="$CONTEXT" -n "$NAMESPACE" get deploy "$d" >/dev/null 2>&1; then
            kubectl --context="$CONTEXT" -n "$NAMESPACE" rollout status deploy/"$d" --timeout=120s
        fi
    done
    echo "  Stateful deps ready."

    # 4. App deployments
    echo ""
    echo "Step 4: Scaling app deployments..."
    kubectl --context="$CONTEXT" -n "$NAMESPACE" scale deploy/tesslate-backend --replicas=1
    kubectl --context="$CONTEXT" -n "$NAMESPACE" scale deploy/tesslate-frontend --replicas=1
    kubectl --context="$CONTEXT" -n "$NAMESPACE" scale deploy/tesslate-worker --replicas=1

    echo ""
    echo "Waiting for app pods..."
    kubectl --context="$CONTEXT" -n "$NAMESPACE" rollout status deploy/tesslate-backend --timeout=120s
    kubectl --context="$CONTEXT" -n "$NAMESPACE" rollout status deploy/tesslate-frontend --timeout=120s
    kubectl --context="$CONTEXT" -n "$NAMESPACE" rollout status deploy/tesslate-worker --timeout=120s
    echo "  All pods ready."

    # 5. Resume CronJobs
    echo ""
    echo "Step 5: Resuming CronJobs..."
    kubectl --context="$CONTEXT" -n "$NAMESPACE" get cronjobs -o name 2>/dev/null | \
        xargs -r -I{} kubectl --context="$CONTEXT" -n "$NAMESPACE" patch {} -p '{"spec":{"suspend":false}}'
    echo "  Done."

    echo ""
    echo "============================================================"
    echo "Migration complete."
    echo ""
    echo "Verify:"
    echo "  1. Volume Hub rebuilt registry from converted manifests"
    echo "     kubectl --context=$CONTEXT -n kube-system logs deploy/tesslate-volume-hub | grep -i rebuild"
    echo ""
    echo "  2. Backend connects to Hub"
    echo "     kubectl --context=$CONTEXT -n $NAMESPACE logs deploy/tesslate-backend | grep -i hub"
    echo ""
    echo "  3. Test a project restore/hibernate cycle in the UI"
    echo "============================================================"
}

# --- Execute ---
if [[ -n "$PHASE" ]]; then
    case "$PHASE" in
        stop)    phase_stop ;;
        backup)  phase_backup ;;
        convert) phase_convert ;;
        deploy)  phase_deploy ;;
        start)   phase_start ;;
        *)       echo "Unknown phase: $PHASE"; usage ;;
    esac
else
    phase_stop
    echo ""
    phase_backup
    echo ""
    phase_convert
    echo ""
    phase_deploy
    echo ""
    phase_start
fi
