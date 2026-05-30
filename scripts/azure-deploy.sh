#!/bin/bash
# =============================================================================
# Azure AKS Deployment Helper Script
# =============================================================================
# Standalone twin of scripts/aws-deploy.sh — same subcommand surface so
# muscle memory carries over, but every Azure call lives here. The two
# scripts never share code paths so AWS changes can't accidentally break
# Azure (and vice versa).
#
# Usage:
#   ./scripts/azure-deploy.sh init production       # Initialize production backend
#   ./scripts/azure-deploy.sh plan production       # Plan production changes
#   ./scripts/azure-deploy.sh apply production      # Apply production changes
#   ./scripts/azure-deploy.sh terraform production  # init → plan → apply
#   ./scripts/azure-deploy.sh destroy production    # Destroy production resources
#   ./scripts/azure-deploy.sh output beta           # Show terraform outputs
#   ./scripts/azure-deploy.sh deploy-k8s beta       # Apply kustomize manifests
#   ./scripts/azure-deploy.sh deploy-compute beta   # Apply compute manifests (CSI + Volume Hub)
#   ./scripts/azure-deploy.sh reload production              # Apply + restart all pods
#   ./scripts/azure-deploy.sh reload production backend      # Restart only backend
#   ./scripts/azure-deploy.sh reload production litellm      # Restart litellm (+ sync config)
#   ./scripts/azure-deploy.sh reload production worker       # Restart worker
#   ./scripts/azure-deploy.sh build beta                       # Build, push, restart
#   ./scripts/azure-deploy.sh build production backend         # Build only backend
#   ./scripts/azure-deploy.sh build beta frontend backend      # Build multiple
#   ./scripts/azure-deploy.sh build beta --cached              # Build with cache
#   ./scripts/azure-deploy.sh build beta compute               # Build compute, deploy + restart
#
# Configuration via env vars (override per-call or in shell profile):
#   AZURE_RESOURCE_GROUP   default: tesslate-${env}-rg
#   AZURE_AKS_CLUSTER      default: tesslate-${env}-aks
#   AZURE_ACR_NAME         REQUIRED for build/push — terraform output `acr_login_server` minus `.azurecr.io`
#   AZURE_REGION           default: eastus
#
# Auth: this script does NOT call `az login` for you. Either log in
# interactively (`az login`) or use a service principal / managed
# identity. The script will fail fast if `az account show` returns nothing.
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

error()   { echo -e "${RED}Error: $1${NC}" >&2; exit 1; }
success() { echo -e "${GREEN}$1${NC}"; }
warning() { echo -e "${YELLOW}$1${NC}"; }
info()    { echo -e "${BLUE}$1${NC}"; }

# =============================================================================
# Shared helpers
# =============================================================================

ensure_az_logged_in() {
    if ! az account show >/dev/null 2>&1; then
        error "Not logged into Azure. Run 'az login' (or set AZURE_* SP env vars and 'az login --service-principal ...')."
    fi
}

# Derive resource group, AKS cluster, and ACR names from ENV + env vars.
# Per-call overrides via AZURE_RESOURCE_GROUP / AZURE_AKS_CLUSTER / AZURE_ACR_NAME.
resolve_azure_names() {
    AZ_RG="${AZURE_RESOURCE_GROUP:-tesslate-${ENVIRONMENT}-rg}"
    AZ_CLUSTER="${AZURE_AKS_CLUSTER:-tesslate-${ENVIRONMENT}-aks}"
    AZ_REGION="${AZURE_REGION:-eastus}"
    # ACR name has a random suffix — terraform output is the source of truth.
    # Caller must export AZURE_ACR_NAME for build/push.
    AZ_ACR="${AZURE_ACR_NAME:-}"
}

ensure_kubectl_context() {
    ensure_az_logged_in
    resolve_azure_names

    info "Configuring kubectl for $AZ_CLUSTER (rg: $AZ_RG)..."
    # --admin returns the AKS-managed client cert kubeconfig, bypassing the
    # AAD device-code prompt. Works whenever `local_account_disabled = false`
    # on the cluster (beta default). Production sets `local_account_disabled
    # = true` and the operator needs `kubelogin` for AAD auth — that path is
    # not driven from this script.
    if ! az aks get-credentials \
            --name "$AZ_CLUSTER" \
            --resource-group "$AZ_RG" \
            --admin \
            --overwrite-existing \
            --only-show-errors >/dev/null 2>&1; then
        error "Failed to fetch AKS credentials. Does cluster '$AZ_CLUSTER' in RG '$AZ_RG' exist? Are you in the right subscription? (az account set --subscription <id>)"
    fi
    # Sanity-check API reachability before any kubectl apply.
    if ! kubectl cluster-info --request-timeout=10s >/dev/null 2>&1; then
        error "Cannot reach cluster $AZ_CLUSTER. Check subscription, Azure RBAC role assignments, and network reachability."
    fi
    success "✓ kubectl context set to $AZ_CLUSTER"
}

apply_kustomize() {
    KUSTOMIZE_DIR="$PROJECT_ROOT/k8s/overlays/azure-${ENVIRONMENT}"
    if [ ! -d "$KUSTOMIZE_DIR" ]; then
        error "Kustomize overlay not found: $KUSTOMIZE_DIR"
    fi

    # Resolve ACR registry from terraform output if not already exported.
    # The overlay carries `tesslateacr.azurecr.io` as a stable placeholder so
    # the manifests are reviewable in git; the real ACR carries a random
    # 8-char suffix per terraform apply (e.g. tesslatebetaacr12ab34cd) so
    # we have to substitute at apply time.
    if [ -z "${AZ_ACR:-}" ]; then
        AZ_ACR=$(terraform -chdir="$TF_DIR" output -raw acr_login_server 2>/dev/null | sed 's/\.azurecr\.io$//' || true)
    fi

    if [ -n "${AZ_ACR:-}" ] && [ "$AZ_ACR" != "tesslateacr" ]; then
        info "Applying kustomize from azure-${ENVIRONMENT} (ACR: ${AZ_ACR}.azurecr.io)..."
        # Substitute the placeholder registry with the real ACR host as we
        # stream through kubectl. Pipe-and-apply preserves dry-run semantics
        # (--dry-run=client works the same way).
        kubectl kustomize "$KUSTOMIZE_DIR" \
            | sed "s|tesslateacr\.azurecr\.io|${AZ_ACR}.azurecr.io|g" \
            | kubectl apply -f -
    else
        info "Applying kustomize manifests from azure-${ENVIRONMENT}..."
        kubectl apply -k "$KUSTOMIZE_DIR"
    fi
    success "✓ Kustomize manifests applied"
}

apply_compute_kustomize() {
    local OVERLAY="$1"
    if [ -z "${AZ_ACR:-}" ]; then
        AZ_ACR=$(terraform -chdir="$TF_DIR" output -raw acr_login_server 2>/dev/null | sed 's/\.azurecr\.io$//' || true)
    fi
    if [ -n "${AZ_ACR:-}" ] && [ "$AZ_ACR" != "tesslateacr" ]; then
        info "Applying compute manifests (ACR: ${AZ_ACR}.azurecr.io)..."
        kubectl kustomize "$OVERLAY" \
            | sed "s|tesslateacr\.azurecr\.io|${AZ_ACR}.azurecr.io|g" \
            | kubectl apply -f -
    else
        kubectl apply -k "$OVERLAY"
    fi
}

restart_pods() {
    local deployments=("$@")
    if [ ${#deployments[@]} -eq 0 ]; then
        deployments=("tesslate-backend" "tesslate-frontend")
    fi

    info "Restarting deployments: ${deployments[*]}..."
    for dep in "${deployments[@]}"; do
        kubectl rollout restart "deployment/${dep}" -n tesslate
    done

    info "Waiting for rollouts..."
    local ROLLOUT_PIDS=()
    local ROLLOUT_NAMES=()
    for dep in "${deployments[@]}"; do
        kubectl rollout status "deployment/${dep}" -n tesslate --timeout=300s &
        ROLLOUT_PIDS+=($!)
        ROLLOUT_NAMES+=("$dep")
    done

    local FAILED=0
    for i in "${!ROLLOUT_PIDS[@]}"; do
        if wait "${ROLLOUT_PIDS[$i]}"; then
            success "[${ROLLOUT_NAMES[$i]}] ✓ Ready"
        else
            echo -e "${RED}[${ROLLOUT_NAMES[$i]}] ✗ Rollout failed${NC}"
            FAILED=1
        fi
    done

    if [ "$FAILED" -ne 0 ]; then
        error "One or more rollouts failed. Check: kubectl get pods -n tesslate"
    fi
}

resolve_deployment_name() {
    case "$1" in
        backend)          echo "tesslate-backend" ;;
        frontend)         echo "tesslate-frontend" ;;
        worker)           echo "tesslate-worker" ;;
        litellm)          echo "litellm" ;;
        redis)            echo "redis" ;;
        pg|postgres)      echo "postgres" ;;
        litellm-pg|litellm-postgres) echo "litellm-postgres" ;;
        volume-hub)       echo "tesslate-volume-hub" ;;
        *)                echo "$1" ;;
    esac
}

sync_litellm_config() {
    local CONFIG_FILE="$PROJECT_ROOT/k8s/litellm/config.yaml"
    if [ ! -f "$CONFIG_FILE" ]; then
        warning "LiteLLM config not found at $CONFIG_FILE, skipping ConfigMap sync"
        return
    fi
    info "Syncing LiteLLM ConfigMap from k8s/litellm/config.yaml..."
    kubectl create configmap litellm-config -n tesslate \
        --from-file=config.yaml="$CONFIG_FILE" \
        --dry-run=client -o yaml | kubectl apply -f -
    success "✓ LiteLLM ConfigMap updated"
}

verify_pods() {
    echo
    info "Verifying deployment..."
    kubectl get pods -n tesslate -o wide | grep -v cleanup
    echo
}

# =============================================================================
# Arg parsing
# =============================================================================
COMMAND="${1:-}"
ENVIRONMENT="${2:-}"

case "$COMMAND" in
    init|plan|apply|destroy|output|state|terraform|deploy-k8s|deploy-compute|build|reload)
        ;;
    *)
        error "Invalid command: $COMMAND\n\nUsage: ./scripts/azure-deploy.sh {init|plan|apply|terraform|destroy|output|state|deploy-k8s|deploy-compute|build|reload} {production|beta}"
        ;;
esac

if [ -z "$ENVIRONMENT" ]; then
    error "Environment not specified.\n\nUsage: ./scripts/azure-deploy.sh $COMMAND {production|beta}"
fi

case "$ENVIRONMENT" in
    production|beta)
        ;;
    *)
        error "Invalid environment: $ENVIRONMENT. Use 'production' or 'beta'."
        ;;
esac

TF_DIR="$PROJECT_ROOT/k8s/terraform/azure"
BACKEND_CONFIG="backend-${ENVIRONMENT}.hcl"
TFVARS_FILE="terraform.${ENVIRONMENT}.tfvars"

# Only cd to terraform dir for terraform commands
if [ "$COMMAND" != "deploy-k8s" ] && [ "$COMMAND" != "deploy-compute" ] && [ "$COMMAND" != "build" ] && [ "$COMMAND" != "reload" ]; then
    cd "$TF_DIR"
fi

# Skip terraform file checks for commands that don't use terraform
if [ "$COMMAND" != "deploy-k8s" ] && [ "$COMMAND" != "deploy-compute" ] && [ "$COMMAND" != "build" ] && [ "$COMMAND" != "reload" ]; then
    if [ ! -f "$BACKEND_CONFIG" ]; then
        error "Backend config not found: $TF_DIR/$BACKEND_CONFIG"
    fi
fi

if [ "$COMMAND" != "state" ] && [ "$COMMAND" != "output" ] && [ "$COMMAND" != "deploy-k8s" ] && [ "$COMMAND" != "deploy-compute" ] && [ "$COMMAND" != "build" ] && [ "$COMMAND" != "reload" ]; then
    if [ ! -f "$TFVARS_FILE" ]; then
        warning "tfvars file not found: $TFVARS_FILE"
        info "Copy terraform.tfvars.example to $TFVARS_FILE and fill in values."
        error "Missing tfvars file"
    fi
fi

# Verify correct backend is loaded
if [ "$COMMAND" != "init" ] && [ "$COMMAND" != "terraform" ] && [ "$COMMAND" != "deploy-k8s" ] && [ "$COMMAND" != "deploy-compute" ] && [ "$COMMAND" != "build" ] && [ "$COMMAND" != "reload" ]; then
    EXPECTED_KEY="${ENVIRONMENT}/terraform.tfstate"
    TF_STATE_FILE=".terraform/terraform.tfstate"
    if [ -f "$TF_STATE_FILE" ]; then
        CURRENT_KEY=$(python3 -c "import json; print(json.load(open('$TF_STATE_FILE')).get('backend',{}).get('config',{}).get('key',''))" 2>/dev/null || echo "")
        if [ "$CURRENT_KEY" != "$EXPECTED_KEY" ]; then
            warning "Backend mismatch! Currently loaded: $CURRENT_KEY"
            warning "Expected for $ENVIRONMENT: $EXPECTED_KEY"
            info "Auto-reinitializing with correct backend..."
            terraform init -reconfigure -backend-config="$BACKEND_CONFIG" >/dev/null 2>&1
            success "✓ Switched to $ENVIRONMENT backend"
        fi
    else
        info "No backend initialized. Running init..."
        terraform init -reconfigure -backend-config="$BACKEND_CONFIG" >/dev/null 2>&1
        success "✓ Initialized $ENVIRONMENT backend"
    fi
fi

if [ "$COMMAND" != "build" ] && [ "$COMMAND" != "reload" ] && [ "$COMMAND" != "deploy-k8s" ] && [ "$COMMAND" != "deploy-compute" ]; then
    info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    info "Cloud:       Azure"
    info "Environment: $ENVIRONMENT"
    info "Command:     $COMMAND"
    info "Backend:     $BACKEND_CONFIG"
    info "Terraform:   $TF_DIR"
    if [ "$COMMAND" != "state" ] && [ "$COMMAND" != "output" ]; then
        info "Variables:   $TFVARS_FILE"
    fi
    info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo
fi

# =============================================================================
# Execute
# =============================================================================
case "$COMMAND" in
    init)
        info "Initializing Terraform for Azure $ENVIRONMENT environment..."

        # Pre-register only the Resource Providers we use. The azurerm provider
        # has `skip_provider_registration = true` so it doesn't try to register
        # ~80 RPs in parallel at startup (which swamps slow DNS resolvers).
        # Registration is idempotent and async — we kick them off in parallel
        # and move on; Azure finishes registering in the background.
        ensure_az_logged_in
        info "Ensuring required Resource Providers are registered..."
        for ns in Microsoft.ContainerService Microsoft.ContainerRegistry Microsoft.Network \
                  Microsoft.Storage Microsoft.DBforPostgreSQL Microsoft.Cache \
                  Microsoft.ManagedIdentity Microsoft.OperationalInsights; do
            state=$(az provider show --namespace "$ns" --query registrationState -o tsv 2>/dev/null || echo Unknown)
            if [ "$state" != "Registered" ]; then
                info "  registering $ns (was: $state)..."
                az provider register --namespace "$ns" --only-show-errors >/dev/null 2>&1 &
            fi
        done
        wait
        success "✓ Resource Providers registered"

        terraform init -reconfigure -backend-config="$BACKEND_CONFIG"
        success "✓ Terraform initialized successfully"
        ;;

    plan)
        info "Planning changes for Azure $ENVIRONMENT environment..."
        terraform plan -var-file="$TFVARS_FILE"
        ;;

    apply)
        warning "⚠️  This will apply changes to Azure $ENVIRONMENT environment"
        read -p "Continue? (yes/no): " -r
        echo
        if [[ ! $REPLY == "yes" ]]; then
            info "Cancelled."
            exit 0
        fi
        info "Applying changes to Azure $ENVIRONMENT environment..."
        terraform apply -var-file="$TFVARS_FILE"
        success "✓ Changes applied successfully"
        ;;

    destroy)
        warning "⚠️  This will DESTROY all Azure resources in $ENVIRONMENT environment"
        warning "⚠️  This action cannot be undone!"
        read -p "Type 'destroy $ENVIRONMENT' to confirm: " -r
        echo
        if [[ ! $REPLY == "destroy $ENVIRONMENT" ]]; then
            info "Cancelled."
            exit 0
        fi
        info "Destroying Azure $ENVIRONMENT environment..."
        terraform destroy -var-file="$TFVARS_FILE"
        success "✓ Resources destroyed"
        ;;

    output)
        terraform output
        ;;

    state)
        info "Terraform state commands:"
        info "  list                    - List resources in state"
        info "  show <resource>         - Show resource details"
        info "  rm <resource>           - Remove resource from state"
        echo
        read -p "Enter state command (or press Enter to list): " -r
        echo
        if [ -z "$REPLY" ]; then
            terraform state list
        else
            terraform state $REPLY
        fi
        ;;

    deploy-k8s)
        ensure_kubectl_context
        apply_kustomize
        echo
        info "Verify with: kubectl get pods -n tesslate"
        ;;

    deploy-compute)
        COMPUTE_OVERLAY="$PROJECT_ROOT/k8s/overlays/azure-${ENVIRONMENT}/compute"
        if [ ! -d "$COMPUTE_OVERLAY" ]; then
            error "Compute overlay not found: $COMPUTE_OVERLAY"
        fi
        ensure_kubectl_context

        info "Applying compute manifests (CSI driver + Volume Hub) from azure-${ENVIRONMENT}/compute..."
        apply_compute_kustomize "$COMPUTE_OVERLAY"
        success "✓ Compute manifests applied"
        echo

        info "Waiting for CSI node daemonset..."
        kubectl rollout status daemonset/tesslate-btrfs-csi-node -n kube-system --timeout=1800s
        info "Waiting for Volume Hub..."
        kubectl rollout status deployment/tesslate-volume-hub -n kube-system --timeout=300s
        success "✓ Compute infrastructure deployed"
        echo
        info "Verify with: kubectl get pods -n kube-system -l 'app in (tesslate-btrfs-csi-node,tesslate-volume-hub)'"
        ;;

    build)
        # Parse optional image arguments and flags
        USE_CACHE=false
        IMAGES=""
        for arg in "${@:3}"; do
            if [ "$arg" = "--cached" ]; then
                USE_CACHE=true
            else
                IMAGES="$IMAGES $arg"
            fi
        done
        IMAGES="${IMAGES# }"
        : "${IMAGES:=backend frontend devserver}"

        ensure_az_logged_in
        resolve_azure_names

        if [ -z "$AZ_ACR" ]; then
            error "AZURE_ACR_NAME not set. Export it (e.g. \$(terraform -chdir=$TF_DIR output -raw acr_login_server | cut -d. -f1)) or set it in your shell profile."
        fi

        ACR_REGISTRY="${AZ_ACR}.azurecr.io"

        # Always build for linux/amd64 — AKS nodes are amd64.
        BUILD_PLATFORM="--platform linux/amd64"

        declare -A DOCKERFILES=(
            [backend]="orchestrator/Dockerfile"
            [frontend]="app/Dockerfile.prod"
            [devserver]="orchestrator/Dockerfile.devserver"
            [compute]="services/btrfs-csi/Dockerfile"
            [ast]="services/ast/Dockerfile"
            [marketplace]="packages/tesslate-marketplace/Dockerfile"
            [markitdown]="seeds/apps/markitdown/Dockerfile"
            [deerflow]="seeds/apps/deer-flow/Dockerfile"
        )
        declare -A BUILD_CONTEXTS=(
            [backend]="."
            [frontend]="app/"
            [devserver]="."
            [compute]="services/btrfs-csi/"
            [ast]="services/ast/"
            [marketplace]="packages/tesslate-marketplace/"
            [markitdown]="seeds/apps/markitdown/"
            [deerflow]="seeds/apps/deer-flow/"
        )
        declare -A K8S_LABELS=(
            [backend]="app=tesslate-backend"
            [frontend]="app=tesslate-frontend"
            [ast]="app=tesslate-backend"
            [marketplace]="app=tesslate-marketplace"
        )
        declare -A ALSO_RESTART=(
            [backend]="tesslate-worker"
            [ast]="tesslate-worker"
        )
        declare -A RESTART_DEPLOY_NAME=(
            [ast]="tesslate-backend"
        )
        declare -A COMPUTE_RESTART=(
            [compute]="1"
        )
        declare -A ACR_REPO_NAME=(
            [compute]="tesslate-btrfs-csi"
        )
        declare -A IMAGE_TAG=(
            [markitdown]="latest"
            [deerflow]="latest"
        )
        declare -A EXTRA_TAGS=(
            [devserver]="latest"
        )

        for img in $IMAGES; do
            case "$img" in
                backend|frontend|devserver|compute|ast|marketplace|markitdown|deerflow) ;;
                *) error "Unknown image: $img. Valid: backend, frontend, devserver, compute, ast, marketplace, markitdown, deerflow" ;;
            esac
        done

        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        info "Cloud:       Azure"
        info "Environment: $ENVIRONMENT"
        info "Command:     build"
        info "Images:      $IMAGES"
        info "Registry:    $ACR_REGISTRY"
        info "Tag:         $ENVIRONMENT"
        info "Platform:    linux/amd64"
        if [ "$USE_CACHE" = true ]; then
            info "Cache:       enabled"
        else
            info "Cache:       disabled (use --cached to enable)"
        fi
        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo

        # Ensure git submodules are present
        if [ -f "$PROJECT_ROOT/.gitmodules" ]; then
            info "Syncing git submodules..."
            (cd "$PROJECT_ROOT" && git submodule update --init --recursive) \
                || error "Failed to initialize git submodules."
            success "✓ Submodules up to date"
            echo
        fi

        # ACR Login via Azure CLI — exchanges AAD token for an ACR refresh token
        # and configures docker to use it. No long-lived ACR admin password.
        info "Logging into ACR..."
        if ! az acr login --name "$AZ_ACR" --only-show-errors >/dev/null 2>&1; then
            error "Failed to log into ACR '$AZ_ACR'. Ensure your AAD identity has AcrPush on the registry."
        fi
        success "✓ ACR login successful"
        echo

        IMAGE_COUNT=$(echo $IMAGES | wc -w)

        if [ "$IMAGE_COUNT" -gt 1 ]; then
            BUILD_PIDS=()
            BUILD_IMGS=()
            BUILD_LOGS=()
            BUILD_TMPDIR=$(mktemp -d)

            for img in $IMAGES; do
                REPO_NAME="${ACR_REPO_NAME[$img]:-tesslate-${img}}"
                TAG="${IMAGE_TAG[$img]:-$ENVIRONMENT}"
                FULL_TAG="${ACR_REGISTRY}/${REPO_NAME}:${TAG}"
                DOCKERFILE="${DOCKERFILES[$img]}"
                CONTEXT="${BUILD_CONTEXTS[$img]}"
                LOG_FILE="$BUILD_TMPDIR/${img}.log"

                CACHE_FLAG="--no-cache"
                if [ "$USE_CACHE" = true ]; then
                    CACHE_FLAG=""
                fi

                EXTRA_TAG_FLAGS=""
                if [ -n "${EXTRA_TAGS[$img]}" ] && [ "${EXTRA_TAGS[$img]}" != "$TAG" ]; then
                    EXTRA_TAG_FLAGS="-t ${ACR_REGISTRY}/${REPO_NAME}:${EXTRA_TAGS[$img]}"
                fi

                info "[$img] Starting build ${FULL_TAG}${EXTRA_TAG_FLAGS:+ + extra tags}..."
                (
                    docker buildx build $BUILD_PLATFORM $CACHE_FLAG -t "$FULL_TAG" $EXTRA_TAG_FLAGS \
                        -f "$PROJECT_ROOT/$DOCKERFILE" "$PROJECT_ROOT/$CONTEXT" --push >>"$LOG_FILE" 2>&1
                ) &
                BUILD_PIDS+=($!)
                BUILD_IMGS+=("$img")
                BUILD_LOGS+=("$LOG_FILE")
            done

            info "Waiting for ${IMAGE_COUNT} parallel builds..."
            echo

            BUILD_FAILED=0
            for i in "${!BUILD_PIDS[@]}"; do
                if wait "${BUILD_PIDS[$i]}"; then
                    success "[${BUILD_IMGS[$i]}] ✓ Build & push complete"
                else
                    echo -e "${RED}[${BUILD_IMGS[$i]}] ✗ Build or push failed. Last 30 lines:${NC}"
                    tail -30 "${BUILD_LOGS[$i]}" 2>/dev/null || true
                    BUILD_FAILED=1
                fi
            done

            rm -rf "$BUILD_TMPDIR"
            echo

            if [ "$BUILD_FAILED" -ne 0 ]; then
                error "One or more builds failed"
            fi
        else
            # Single image — inline build with live output
            for img in $IMAGES; do
                REPO_NAME="${ACR_REPO_NAME[$img]:-tesslate-${img}}"
                TAG="${IMAGE_TAG[$img]:-$ENVIRONMENT}"
                FULL_TAG="${ACR_REGISTRY}/${REPO_NAME}:${TAG}"
                DOCKERFILE="${DOCKERFILES[$img]}"
                CONTEXT="${BUILD_CONTEXTS[$img]}"

                CACHE_FLAG="--no-cache"
                if [ "$USE_CACHE" = true ]; then
                    CACHE_FLAG=""
                fi

                EXTRA_TAG_FLAGS=""
                if [ -n "${EXTRA_TAGS[$img]}" ] && [ "${EXTRA_TAGS[$img]}" != "$TAG" ]; then
                    EXTRA_TAG_FLAGS="-t ${ACR_REGISTRY}/${REPO_NAME}:${EXTRA_TAGS[$img]}"
                fi

                info "[$img] Building ${FULL_TAG}${EXTRA_TAG_FLAGS:+ + extra tags}..."
                docker buildx build $BUILD_PLATFORM $CACHE_FLAG -t "$FULL_TAG" $EXTRA_TAG_FLAGS \
                    -f "$PROJECT_ROOT/$DOCKERFILE" "$PROJECT_ROOT/$CONTEXT" --push
                success "[$img] ✓ Build & push complete"
                echo
            done
        fi

        # Switch context, apply manifests, and restart pods
        ensure_kubectl_context
        echo

        info "Applying kustomize manifests..."
        apply_kustomize
        echo

        info "Restarting pods..."
        RESTART_DEPLOYMENTS=()
        RESTART_NAMES=()
        declare -A SEEN_DEPLOY=()
        for img in $IMAGES; do
            if [ -n "${COMPUTE_RESTART[$img]:-}" ]; then
                continue
            fi
            LABEL="${K8S_LABELS[$img]:-}"
            if [ -n "$LABEL" ]; then
                DEPLOY_NAME="${RESTART_DEPLOY_NAME[$img]:-tesslate-${img}}"
                if [ -z "${SEEN_DEPLOY[$DEPLOY_NAME]:-}" ]; then
                    SEEN_DEPLOY[$DEPLOY_NAME]=1
                    RESTART_DEPLOYMENTS+=("$DEPLOY_NAME")
                    RESTART_NAMES+=("$img")
                fi
            fi
            EXTRA="${ALSO_RESTART[$img]:-}"
            if [ -n "$EXTRA" ]; then
                if [ -z "${SEEN_DEPLOY[$EXTRA]:-}" ]; then
                    SEEN_DEPLOY[$EXTRA]=1
                    RESTART_DEPLOYMENTS+=("$EXTRA")
                    RESTART_NAMES+=("${EXTRA#tesslate-}")
                fi
            fi
        done

        for i in "${!RESTART_DEPLOYMENTS[@]}"; do
            info "[${RESTART_NAMES[$i]}] Rolling restart..."
            kubectl rollout restart "deployment/${RESTART_DEPLOYMENTS[$i]}" -n tesslate
        done

        ROLLOUT_PIDS=()
        ROLLOUT_IMGS=()
        for i in "${!RESTART_DEPLOYMENTS[@]}"; do
            info "[${RESTART_NAMES[$i]}] Waiting for rollout..."
            kubectl rollout status "deployment/${RESTART_DEPLOYMENTS[$i]}" -n tesslate --timeout=300s &
            ROLLOUT_PIDS+=($!)
            ROLLOUT_IMGS+=("${RESTART_NAMES[$i]}")
        done

        # Compute image rolls CSI DaemonSet then Volume Hub — same sequencing
        # rules as the AWS script: Hub must wait for CSI nodes to be stable.
        for img in $IMAGES; do
            if [ -n "${COMPUTE_RESTART[$img]:-}" ]; then
                info "[compute] Applying compute manifests..."
                apply_compute_kustomize "$PROJECT_ROOT/k8s/overlays/azure-${ENVIRONMENT}/compute"
                info "[compute] Rolling restart CSI node daemonset (Hub will follow once nodes stable)..."
                kubectl rollout restart daemonset/tesslate-btrfs-csi-node -n kube-system
                (
                    kubectl rollout status daemonset/tesslate-btrfs-csi-node -n kube-system --timeout=1800s || exit $?
                    echo "[compute] CSI nodes stable, restarting Volume Hub..."
                    kubectl rollout restart deployment/tesslate-volume-hub -n kube-system || exit $?
                    kubectl rollout status deployment/tesslate-volume-hub -n kube-system --timeout=300s
                ) &
                ROLLOUT_PIDS+=($!)
                ROLLOUT_IMGS+=("compute(csi+hub)")
            fi
        done

        FAILED=0
        for i in "${!ROLLOUT_PIDS[@]}"; do
            if wait "${ROLLOUT_PIDS[$i]}"; then
                success "[${ROLLOUT_IMGS[$i]}] ✓ Ready"
            else
                echo -e "${RED}[${ROLLOUT_IMGS[$i]}] ✗ Rollout failed${NC}"
                FAILED=1
            fi
        done

        if [ "$FAILED" -ne 0 ]; then
            error "One or more rollouts failed. Check: kubectl get pods -n tesslate -n kube-system"
        fi

        # Seed Tesslate Apps registry — mirrors aws-deploy.sh
        case " $IMAGES " in
            *" backend "*)
                info "Seeding Tesslate Apps registry..."
                if kubectl exec -n tesslate deploy/tesslate-backend -- \
                    python -m scripts.seed_apps; then
                    success "✓ Apps registry seeded"
                else
                    warning "Apps registry seed reported failures — inspect backend logs"
                fi
                echo
                ;;
        esac

        verify_pods
        success "✓ Build and deploy complete for Azure $ENVIRONMENT!"
        ;;

    reload)
        TARGETS=""
        for arg in "${@:3}"; do
            TARGETS="$TARGETS $arg"
        done
        TARGETS="${TARGETS# }"

        ensure_kubectl_context

        DEPLOYMENTS=()
        KUBE_SYSTEM_TARGETS=()
        SYNC_LITELLM=false
        if [ -z "$TARGETS" ]; then
            DEPLOYMENTS=("tesslate-backend" "tesslate-frontend" "tesslate-worker")
            APPLY_MANIFESTS=true
        else
            APPLY_MANIFESTS=false
            for target in $TARGETS; do
                if [ "$target" = "volume-hub" ]; then
                    KUBE_SYSTEM_TARGETS+=("deployment/tesslate-volume-hub")
                    continue
                fi
                dep=$(resolve_deployment_name "$target")
                DEPLOYMENTS+=("$dep")
                if [ "$target" = "litellm" ]; then
                    SYNC_LITELLM=true
                fi
            done
        fi

        DISPLAY_TARGETS="${TARGETS:-all}"
        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        info "Cloud:       Azure"
        info "Environment: $ENVIRONMENT"
        info "Command:     reload"
        info "Targets:     $DISPLAY_TARGETS"
        info "Cluster:     $AZ_CLUSTER"
        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo

        STEP=1
        TOTAL_STEPS=1
        if [ "$APPLY_MANIFESTS" = true ]; then TOTAL_STEPS=$((TOTAL_STEPS + 1)); fi
        if [ "$SYNC_LITELLM" = true ]; then TOTAL_STEPS=$((TOTAL_STEPS + 1)); fi

        if [ "$APPLY_MANIFESTS" = true ]; then
            info "Step ${STEP}/${TOTAL_STEPS}: Applying kustomize manifests..."
            apply_kustomize
            echo
            STEP=$((STEP + 1))
        fi

        if [ "$SYNC_LITELLM" = true ]; then
            info "Step ${STEP}/${TOTAL_STEPS}: Syncing LiteLLM config..."
            sync_litellm_config
            echo
            STEP=$((STEP + 1))
        fi

        info "Step ${STEP}/${TOTAL_STEPS}: Restarting pods..."
        if [ ${#DEPLOYMENTS[@]} -gt 0 ]; then
            restart_pods "${DEPLOYMENTS[@]}"
        fi
        for ks_target in "${KUBE_SYSTEM_TARGETS[@]}"; do
            info "Restarting ${ks_target} in kube-system..."
            kubectl rollout restart "${ks_target}" -n kube-system
            kubectl rollout status "${ks_target}" -n kube-system --timeout=300s
            success "[${ks_target##*/}] ✓ Ready"
        done
        verify_pods
        success "✓ Reload complete for Azure $ENVIRONMENT!"
        ;;

    terraform)
        info "Running full Terraform deployment for Azure $ENVIRONMENT environment..."
        info "This will: init → plan → apply"
        echo

        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        info "Step 1/3: Initializing Terraform..."
        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        terraform init -reconfigure -backend-config="$BACKEND_CONFIG"
        success "✓ Initialization complete"
        echo

        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        info "Step 2/3: Planning changes..."
        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        terraform plan -var-file="$TFVARS_FILE" -out=tfplan
        echo

        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        info "Step 3/3: Apply changes"
        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        warning "⚠️  Ready to apply changes to Azure $ENVIRONMENT environment"
        read -p "Continue with apply? (yes/no): " -r
        echo
        if [[ ! $REPLY == "yes" ]]; then
            info "Cancelled. Plan saved to tfplan"
            info "You can apply later with: cd $TF_DIR && terraform apply tfplan"
            exit 0
        fi

        info "Applying changes to Azure $ENVIRONMENT environment..."
        terraform apply tfplan
        rm -f tfplan
        success "✓ Deployment complete!"
        echo
        info "Run './scripts/azure-deploy.sh output $ENVIRONMENT' to see outputs"
        ;;
esac
