#!/bin/bash
# =============================================================================
# AWS EKS Deployment Helper Script
# =============================================================================
# Manages Terraform infrastructure, Docker image builds, and K8s deployments.
#
# Usage:
#   ./scripts/aws-deploy.sh init production       # Initialize production backend
#   ./scripts/aws-deploy.sh plan production        # Plan production changes
#   ./scripts/aws-deploy.sh apply production       # Apply production changes
#   ./scripts/aws-deploy.sh terraform production   # Run init → plan → apply (full deployment)
#   ./scripts/aws-deploy.sh destroy production     # Destroy production resources
#   ./scripts/aws-deploy.sh output beta            # Show terraform outputs
#   ./scripts/aws-deploy.sh deploy-k8s beta        # Apply kustomize manifests for environment
#   ./scripts/aws-deploy.sh reload production               # Apply manifests + restart all pods
#   ./scripts/aws-deploy.sh reload production backend      # Restart only backend
#   ./scripts/aws-deploy.sh reload production litellm      # Restart only litellm (+ sync config)
#   ./scripts/aws-deploy.sh reload production worker       # Restart only worker
#   ./scripts/aws-deploy.sh reload production redis        # Restart only redis
#   ./scripts/aws-deploy.sh reload production pg           # Restart only postgres (alias: postgres)
#   ./scripts/aws-deploy.sh reload production litellm-pg   # Restart only litellm-postgres
#   ./scripts/aws-deploy.sh reload production backend litellm  # Restart multiple pods
#   ./scripts/aws-deploy.sh build beta                       # Build, push, restart all images
#   ./scripts/aws-deploy.sh build production backend         # Build only backend
#   ./scripts/aws-deploy.sh build beta frontend backend      # Build multiple images
#   ./scripts/aws-deploy.sh build beta --cached              # Build with Docker cache
#   ./scripts/aws-deploy.sh build beta compute               # Build compute image, deploy + restart
#   ./scripts/aws-deploy.sh deploy-compute beta              # Apply compute manifests (CSI + Volume Hub)
#   ./scripts/aws-deploy.sh build beta backend --cached      # Build only backend with cache
#   ./scripts/aws-deploy.sh build production marketplace --cached  # Build only marketplace
#
# Role selection (kubectl-using commands only):
#   Default role is `team-admin` for the target environment so cluster-mutating
#   ops (deploy-k8s, deploy-compute) work out of the box. Override per-call:
#     --role observer   # read-only (logs, get, describe)
#     --role deployer   # rollouts + ECR push (least-privilege for `build`/`reload`)
#     --role debugger   # deployer + exec / debug containers
#     --role admin      # default — RBAC, ServiceAccounts, NetworkPolicies, secrets
#     --role eks-deployer  # legacy admin role (gated by eks_admin_iam_arns)
#   Or set AWS_EKS_ROLE_ARN=<full ARN> for cross-account / non-team roles.
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
error() {
    echo -e "${RED}Error: $1${NC}" >&2
    exit 1
}

success() {
    echo -e "${GREEN}$1${NC}"
}

warning() {
    echo -e "${YELLOW}$1${NC}"
}

info() {
    echo -e "${BLUE}$1${NC}"
}

# =============================================================================
# Shared helpers for K8s operations
# =============================================================================

ensure_kubectl_context() {
    if [ "$ENVIRONMENT" = "shared" ]; then
        CLUSTER_NAME="tesslate-platform-eks"
    else
        CLUSTER_NAME="tesslate-${ENVIRONMENT}-eks"
    fi
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")

    # Role precedence: AWS_EKS_ROLE_ARN (full ARN) > --role short name > default "admin".
    # Default is admin so cluster-mutating ops (deploy-k8s, deploy-compute) work
    # out of the box; pass --role deployer for least-privilege image rollouts.
    # See docs/guides/eks-cluster-access.md for the full role matrix.
    if [ -n "$AWS_EKS_ROLE_ARN" ]; then
        ROLE_ARN="$AWS_EKS_ROLE_ARN"
    else
        local short_role="${EXPLICIT_ROLE:-admin}"
        case "$short_role" in
            observer|deployer|debugger|admin)
                ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${CLUSTER_NAME}-team-${short_role}"
                ;;
            eks-deployer)
                # Legacy admin role gated by eks_admin_iam_arns. Use only if
                # you are explicitly listed there (terraform, bigboss).
                ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${CLUSTER_NAME}-eks-deployer"
                ;;
            *)
                error "Invalid --role: '$short_role'. Use one of: observer, deployer, debugger, admin (or 'eks-deployer' for the legacy admin role)."
                ;;
        esac
    fi
    ROLE_NAME="${ROLE_ARN##*/}"

    info "Configuring kubectl for $CLUSTER_NAME (via role: ${ROLE_NAME})..."
    aws eks update-kubeconfig --region us-east-1 --name "$CLUSTER_NAME" --alias "$CLUSTER_NAME" \
        --role-arn "$ROLE_ARN" >/dev/null 2>&1 \
        || error "Failed to configure kubectl. Does cluster '$CLUSTER_NAME' exist? Can you assume role '$ROLE_ARN'? (Try a different --role or set AWS_EKS_ROLE_ARN to a full ARN.)"
    success "✓ kubectl context set to $CLUSTER_NAME (role: ${ROLE_NAME})"

    if ! kubectl cluster-info --request-timeout=10s >/dev/null 2>&1; then
        error "Cannot reach cluster $CLUSTER_NAME. Check AWS credentials and role permissions."
    fi
}

apply_kustomize() {
    KUSTOMIZE_DIR="$PROJECT_ROOT/k8s/overlays/aws-${ENVIRONMENT}"

    if [ ! -d "$KUSTOMIZE_DIR" ]; then
        error "Kustomize overlay not found: $KUSTOMIZE_DIR"
    fi

    info "Applying kustomize manifests from aws-${ENVIRONMENT}..."
    kubectl apply -k "$KUSTOMIZE_DIR"
    success "✓ Kustomize manifests applied"
}

restart_pods() {
    # Accept deployment names as arguments, default to backend + frontend
    local deployments=("${@:-tesslate-backend tesslate-frontend}")
    if [ $# -eq 0 ]; then
        deployments=("tesslate-backend" "tesslate-frontend")
    fi

    info "Restarting deployments: ${deployments[*]}..."
    for dep in "${deployments[@]}"; do
        kubectl rollout restart "deployment/${dep}" -n tesslate
    done

    info "Waiting for rollouts..."
    local ROLLOUT_PIDS=()
    local ROLLOUT_NAMES=()
    # 300s covers a cold image pull of a 400 MB image on a fresh EKS
    # node (typically ~60s) plus app startup + probe ramp. Subsequent
    # rollouts of the same tag are cache-hot (~10s).
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

# Map short names to K8s deployment names
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

# Parse arguments
COMMAND="${1:-}"
ENVIRONMENT="${2:-}"

# Strip --role {observer|deployer|debugger|admin|eks-deployer} from the
# remaining args before the per-command parsers (build/reload) consume
# ${@:3}. Resolved later in ensure_kubectl_context.
EXPLICIT_ROLE=""
if [ $# -ge 2 ]; then
    POSITIONAL=("$1" "$2")
    shift 2
    while [ $# -gt 0 ]; do
        case "$1" in
            --role)
                if [ $# -lt 2 ]; then
                    error "--role requires a value: observer|deployer|debugger|admin|eks-deployer"
                fi
                EXPLICIT_ROLE="$2"
                shift 2
                ;;
            --role=*)
                EXPLICIT_ROLE="${1#--role=}"
                shift
                ;;
            *)
                POSITIONAL+=("$1")
                shift
                ;;
        esac
    done
    set -- "${POSITIONAL[@]}"
fi

# Validate command
case "$COMMAND" in
    init|plan|apply|destroy|output|state|terraform|deploy-k8s|deploy-compute|build|reload)
        ;;
    *)
        error "Invalid command: $COMMAND\n\nUsage: ./scripts/aws-deploy.sh {init|plan|apply|terraform|destroy|output|state|deploy-k8s|deploy-compute|build|reload} {production|beta|shared} [--role observer|deployer|debugger|admin]"
        ;;
esac

# Validate environment
if [ -z "$ENVIRONMENT" ]; then
    error "Environment not specified.\n\nUsage: ./scripts/aws-deploy.sh $COMMAND {production|beta|shared}"
fi

case "$ENVIRONMENT" in
    production|beta|shared)
        ;;
    *)
        error "Invalid environment: $ENVIRONMENT. Use 'production', 'beta', or 'shared'"
        ;;
esac

# Set directory and files based on environment
case "$ENVIRONMENT" in
    shared)
        TF_DIR="$PROJECT_ROOT/k8s/terraform/shared"
        BACKEND_CONFIG="backend.hcl"
        TFVARS_FILE="terraform.shared.tfvars"
        ;;
    *)
        TF_DIR="$PROJECT_ROOT/k8s/terraform/aws"
        BACKEND_CONFIG="backend-${ENVIRONMENT}.hcl"
        TFVARS_FILE="terraform.${ENVIRONMENT}.tfvars"
        ;;
esac

# Only cd to terraform dir for terraform commands
if [ "$COMMAND" != "deploy-k8s" ] && [ "$COMMAND" != "deploy-compute" ] && [ "$COMMAND" != "build" ] && [ "$COMMAND" != "reload" ]; then
    cd "$TF_DIR"
fi

# Skip terraform file checks for commands that don't use terraform
if [ "$COMMAND" != "deploy-k8s" ] && [ "$COMMAND" != "deploy-compute" ] && [ "$COMMAND" != "build" ] && [ "$COMMAND" != "reload" ]; then
    # Check if backend config exists
    if [ ! -f "$BACKEND_CONFIG" ]; then
        error "Backend config not found: $TF_DIR/$BACKEND_CONFIG"
    fi
fi

# Check if tfvars file exists (except for state/output/deploy-k8s commands)
if [ "$COMMAND" != "state" ] && [ "$COMMAND" != "output" ] && [ "$COMMAND" != "deploy-k8s" ] && [ "$COMMAND" != "deploy-compute" ] && [ "$COMMAND" != "build" ] && [ "$COMMAND" != "reload" ]; then
    if [ ! -f "$TFVARS_FILE" ]; then
        warning "tfvars file not found: $TFVARS_FILE"
        info "Download from AWS Secrets Manager with:"
        info "  ./scripts/terraform/secrets.sh download $ENVIRONMENT"
        error "Missing tfvars file"
    fi
fi

# Verify correct backend is loaded (skip for init, all, and deploy-k8s which don't need terraform)
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

# Display environment info (build/reload/deploy-k8s show their own or minimal summary)
if [ "$COMMAND" != "build" ] && [ "$COMMAND" != "reload" ] && [ "$COMMAND" != "deploy-k8s" ] && [ "$COMMAND" != "deploy-compute" ]; then
    info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
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

# Execute command
case "$COMMAND" in
    init)
        info "Initializing Terraform for $ENVIRONMENT environment..."
        terraform init -reconfigure -backend-config="$BACKEND_CONFIG"
        success "✓ Terraform initialized successfully"
        ;;

    plan)
        info "Planning changes for $ENVIRONMENT environment..."
        terraform plan -var-file="$TFVARS_FILE"
        ;;

    apply)
        warning "⚠️  This will apply changes to $ENVIRONMENT environment"
        read -p "Continue? (yes/no): " -r
        echo
        if [[ ! $REPLY == "yes" ]]; then
            info "Cancelled."
            exit 0
        fi
        info "Applying changes to $ENVIRONMENT environment..."
        terraform apply -var-file="$TFVARS_FILE"
        success "✓ Changes applied successfully"
        ;;

    destroy)
        warning "⚠️  This will DESTROY all resources in $ENVIRONMENT environment"
        warning "⚠️  This action cannot be undone!"
        read -p "Type 'destroy $ENVIRONMENT' to confirm: " -r
        echo
        if [[ ! $REPLY == "destroy $ENVIRONMENT" ]]; then
            info "Cancelled."
            exit 0
        fi
        info "Destroying $ENVIRONMENT environment..."
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
        if [ "$ENVIRONMENT" = "shared" ]; then
            error "deploy-k8s is not available for $ENVIRONMENT environment (Helm-managed only)"
        fi

        ensure_kubectl_context
        apply_kustomize
        echo
        info "Verify with: kubectl get pods -n tesslate"
        ;;

    deploy-compute)
        if [ "$ENVIRONMENT" = "shared" ]; then
            error "deploy-compute is not available for $ENVIRONMENT environment"
        fi

        COMPUTE_OVERLAY="$PROJECT_ROOT/k8s/overlays/aws-${ENVIRONMENT}/compute"
        if [ ! -d "$COMPUTE_OVERLAY" ]; then
            error "Compute overlay not found: $COMPUTE_OVERLAY"
        fi

        ensure_kubectl_context
        info "Applying compute manifests (CSI driver + Volume Hub) from aws-${ENVIRONMENT}/compute..."
        kubectl apply -k "$COMPUTE_OVERLAY"
        success "✓ Compute manifests applied"
        echo

        info "Waiting for CSI node daemonset..."
        kubectl rollout status daemonset/tesslate-btrfs-csi-node -n kube-system --timeout=1800s
        info "Waiting for Volume Hub (includes CSI controller)..."
        kubectl rollout status deployment/tesslate-volume-hub -n kube-system --timeout=300s
        success "✓ Compute infrastructure deployed"
        echo
        info "Verify with: kubectl get pods -n kube-system -l 'app in (tesslate-btrfs-csi-node,tesslate-volume-hub)'"
        ;;

    build)
        # Build is only for production/beta
        if [ "$ENVIRONMENT" = "shared" ]; then
            error "Build is not available for $ENVIRONMENT environment"
        fi

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
        IMAGES="${IMAGES# }"  # trim leading space
        : "${IMAGES:=backend frontend devserver}"

        # ECR config
        ECR_ACCOUNT="<AWS_ACCOUNT_ID>"
        ECR_REGISTRY="${ECR_ACCOUNT}.dkr.ecr.us-east-1.amazonaws.com"

        # Always build for linux/amd64 — EKS nodes are amd64.
        # Without this, builds on Apple Silicon produce arm64 images that
        # fail with "no match for platform in manifest" on EKS.
        BUILD_PLATFORM="--platform linux/amd64"

        # Image definitions
        declare -A DOCKERFILES=(
            [backend]="orchestrator/Dockerfile"
            [frontend]="app/Dockerfile.prod"
            [devserver]="orchestrator/Dockerfile.devserver"
            [compute]="services/btrfs-csi/Dockerfile"
            [ast]="services/ast/Dockerfile"
            # Federated /v1 marketplace service. Built from its own
            # subtree so the orchestrator image stays small.
            [marketplace]="packages/tesslate-marketplace/Dockerfile"
            # Seeded Tesslate Apps — external images mirrored to ECR so EKS
            # nodes can pull (short names in manifests get prefixed via
            # APP_IMAGE_REGISTRY_PREFIX at install time). mirofish is pulled
            # directly from public ghcr.io and doesn't need a build entry.
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
            # AST rides as a sidecar in the backend pod — rolling the
            # backend deployment is what picks up a new tesslate-ast image.
            [ast]="app=tesslate-backend"
            [marketplace]="app=tesslate-marketplace"
        )
        # Additional deployments to restart when a given image is built
        # (e.g., worker uses the same image as backend)
        declare -A ALSO_RESTART=(
            [backend]="tesslate-worker"
            [ast]="tesslate-worker"
        )
        # Override the restart-target deployment name when it differs
        # from tesslate-${img}. AST pushes to tesslate-ast ECR repo but
        # the K8s deployment to restart is tesslate-backend.
        declare -A RESTART_DEPLOY_NAME=(
            [ast]="tesslate-backend"
        )
        # Compute image uses kube-system namespace (CSI driver + Volume Hub)
        declare -A COMPUTE_RESTART=(
            [compute]="1"
        )
        # ECR repo name override (compute image pushes to tesslate-btrfs-csi repo)
        declare -A ECR_REPO_NAME=(
            [compute]="tesslate-btrfs-csi"
        )
        # Tag override — seed app manifests hardcode ":latest" (they're content
        # fixtures, not rolled per-env), so push them as :latest instead of
        # :$ENVIRONMENT. App/backend images still use the env-specific tag.
        declare -A IMAGE_TAG=(
            [markitdown]="latest"
            [deerflow]="latest"
        )

        # Validate image names
        for img in $IMAGES; do
            case "$img" in
                backend|frontend|devserver|compute|ast|marketplace|markitdown|deerflow) ;;
                *) error "Unknown image: $img. Valid: backend, frontend, devserver, compute, ast, marketplace, markitdown, deerflow" ;;
            esac
        done

        # Summary
        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        info "Environment: $ENVIRONMENT"
        info "Command:     build"
        info "Images:      $IMAGES"
        info "Registry:    $ECR_REGISTRY"
        info "Tag:         $ENVIRONMENT"
        info "Platform:    linux/amd64"
        if [ "$USE_CACHE" = true ]; then
            info "Cache:       enabled"
        else
            info "Cache:       disabled (use --cached to enable)"
        fi
        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo

        # Ensure git submodules are present on disk — the orchestrator
        # Dockerfile COPYs packages/tesslate-agent into the image and pip
        # installs it. An uninitialized submodule yields an empty
        # directory, shipping a broken image that fails every agent run
        # with "No module named 'tesslate_agent'".
        if [ -f "$PROJECT_ROOT/.gitmodules" ]; then
            info "Syncing git submodules..."
            (cd "$PROJECT_ROOT" && git submodule update --init --recursive) \
                || error "Failed to initialize git submodules. Check network access and credentials for submodule URLs in .gitmodules."
            success "✓ Submodules up to date"
            echo
        fi

        # ECR Login
        info "Logging into ECR..."
        aws ecr get-login-password --region us-east-1 \
            | docker login --username AWS --password-stdin "$ECR_REGISTRY" 2>/dev/null
        success "✓ ECR login successful"
        echo

        # Build & Push
        IMAGE_COUNT=$(echo $IMAGES | wc -w)

        if [ "$IMAGE_COUNT" -gt 1 ]; then
            # Parallel builds
            BUILD_PIDS=()
            BUILD_IMGS=()
            BUILD_LOGS=()
            BUILD_TMPDIR=$(mktemp -d)

            for img in $IMAGES; do
                REPO_NAME="${ECR_REPO_NAME[$img]:-tesslate-${img}}"
                TAG="${IMAGE_TAG[$img]:-$ENVIRONMENT}"
                FULL_TAG="${ECR_REGISTRY}/${REPO_NAME}:${TAG}"
                DOCKERFILE="${DOCKERFILES[$img]}"
                CONTEXT="${BUILD_CONTEXTS[$img]}"
                LOG_FILE="$BUILD_TMPDIR/${img}.log"

                CACHE_FLAG="--no-cache"
                if [ "$USE_CACHE" = true ]; then
                    CACHE_FLAG=""
                fi

                info "[$img] Starting build ${FULL_TAG}..."
                (
                    docker buildx build $BUILD_PLATFORM $CACHE_FLAG -t "$FULL_TAG" \
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
            # Single image — build inline with live output
            for img in $IMAGES; do
                REPO_NAME="${ECR_REPO_NAME[$img]:-tesslate-${img}}"
                TAG="${IMAGE_TAG[$img]:-$ENVIRONMENT}"
                FULL_TAG="${ECR_REGISTRY}/${REPO_NAME}:${TAG}"
                DOCKERFILE="${DOCKERFILES[$img]}"
                CONTEXT="${BUILD_CONTEXTS[$img]}"

                CACHE_FLAG="--no-cache"
                if [ "$USE_CACHE" = true ]; then
                    CACHE_FLAG=""
                fi

                info "[$img] Building ${FULL_TAG}..."
                docker buildx build $BUILD_PLATFORM $CACHE_FLAG -t "$FULL_TAG" \
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
        # Collect all deployments to restart (primary + additional),
        # deduplicating by deployment name. Multiple images can target
        # the same deployment (e.g. `ast` and `backend` both roll the
        # backend Deployment because AST is a sidecar inside it, and
        # `backend` + `ast` both trigger worker restart via
        # ALSO_RESTART). Without dedup we'd queue two sequential
        # rollouts on the same object, each draining for up to the
        # full terminationGracePeriodSeconds.
        RESTART_DEPLOYMENTS=()
        RESTART_NAMES=()
        declare -A SEEN_DEPLOY=()
        for img in $IMAGES; do
            # Compute image restarts are in kube-system, not tesslate
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

        # Wait for rollouts in parallel
        ROLLOUT_PIDS=()
        ROLLOUT_IMGS=()
        for i in "${!RESTART_DEPLOYMENTS[@]}"; do
            info "[${RESTART_NAMES[$i]}] Waiting for rollout..."
            kubectl rollout status "deployment/${RESTART_DEPLOYMENTS[$i]}" -n tesslate --timeout=300s &
            ROLLOUT_PIDS+=($!)
            ROLLOUT_IMGS+=("${RESTART_NAMES[$i]}")
        done

        # Handle compute image restarts (kube-system: CSI node + Volume Hub).
        # Hub MUST restart only after the CSI DaemonSet rollout finishes:
        # restarting Hub while CSI pods are still draining causes the new Hub
        # to rebuild its registry without the terminating node, which hangs
        # the in-flight drain RPC on a broken gRPC connection and stalls the
        # pod for the full 10-minute terminationGracePeriodSeconds.
        for img in $IMAGES; do
            if [ -n "${COMPUTE_RESTART[$img]:-}" ]; then
                info "[compute] Applying compute manifests..."
                kubectl apply -k "$PROJECT_ROOT/k8s/overlays/aws-${ENVIRONMENT}/compute"
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

        # Seed / upsert the Tesslate Apps registry — mirrors what
        # scripts/seed_all_apps.sh does on minikube. Runs only when the
        # backend was rolled (the image the seeder runs in was just
        # rebuilt, so manifest changes land with their deploy). Idempotent:
        # the runner upserts rows by slug+version and skips unchanged apps.
        # Skipped entirely if backend wasn't in the build set (e.g. when
        # the invoker only rebuilt `ast` or `compute`).
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
        success "✓ Build and deploy complete for $ENVIRONMENT!"
        ;;

    reload)
        if [ "$ENVIRONMENT" = "shared" ]; then
            error "Reload is not available for $ENVIRONMENT environment"
        fi

        # Parse target pods from remaining args
        TARGETS=""
        for arg in "${@:3}"; do
            TARGETS="$TARGETS $arg"
        done
        TARGETS="${TARGETS# }"

        ensure_kubectl_context

        # Resolve short names to deployment names
        DEPLOYMENTS=()
        KUBE_SYSTEM_TARGETS=()
        SYNC_LITELLM=false
        if [ -z "$TARGETS" ]; then
            # No specific targets — reload all (apply manifests + restart backend/frontend/worker)
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
        info "Environment: $ENVIRONMENT"
        info "Command:     reload"
        info "Targets:     $DISPLAY_TARGETS"
        info "Cluster:     tesslate-${ENVIRONMENT}-eks"
        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo

        STEP=1
        TOTAL_STEPS=1
        if [ "$APPLY_MANIFESTS" = true ]; then
            TOTAL_STEPS=$((TOTAL_STEPS + 1))
        fi
        if [ "$SYNC_LITELLM" = true ]; then
            TOTAL_STEPS=$((TOTAL_STEPS + 1))
        fi

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
        # Handle kube-system targets (Volume Hub, etc.)
        for ks_target in "${KUBE_SYSTEM_TARGETS[@]}"; do
            info "Restarting ${ks_target} in kube-system..."
            kubectl rollout restart "${ks_target}" -n kube-system
            kubectl rollout status "${ks_target}" -n kube-system --timeout=300s
            success "[${ks_target##*/}] ✓ Ready"
        done
        verify_pods
        success "✓ Reload complete for $ENVIRONMENT!"
        ;;

    terraform)
        info "Running full Terraform deployment for $ENVIRONMENT environment..."
        info "This will: init → plan → apply"
        echo

        # Step 1: Init
        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        info "Step 1/3: Initializing Terraform..."
        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        terraform init -reconfigure -backend-config="$BACKEND_CONFIG"
        success "✓ Initialization complete"
        echo

        # Step 2: Plan
        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        info "Step 2/3: Planning changes..."
        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        terraform plan -var-file="$TFVARS_FILE" -out=tfplan
        echo

        # Step 3: Apply (with confirmation)
        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        info "Step 3/3: Apply changes"
        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        warning "⚠️  Ready to apply changes to $ENVIRONMENT environment"
        read -p "Continue with apply? (yes/no): " -r
        echo
        if [[ ! $REPLY == "yes" ]]; then
            info "Cancelled. Plan saved to tfplan"
            info "You can apply later with: cd $TF_DIR && terraform apply tfplan"
            exit 0
        fi

        info "Applying changes to $ENVIRONMENT environment..."
        terraform apply tfplan
        rm -f tfplan
        success "✓ Deployment complete!"
        echo
        info "Run './scripts/aws-deploy.sh output $ENVIRONMENT' to see outputs"
        ;;
esac
