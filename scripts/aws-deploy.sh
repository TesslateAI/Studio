#!/bin/bash
# =============================================================================
# AWS EKS Deployment Helper Script
# =============================================================================
# Manages Terraform infrastructure, Docker image builds, and K8s deployments.
#
# Usage:
#   ./scripts/aws-deploy.sh init production    # Initialize production backend
#   ./scripts/aws-deploy.sh plan production     # Plan production changes
#   ./scripts/aws-deploy.sh apply production    # Apply production changes
#   ./scripts/aws-deploy.sh all production      # Run init → plan → apply (full deployment)
#   ./scripts/aws-deploy.sh destroy production  # Destroy production resources
#   ./scripts/aws-deploy.sh output beta         # Show terraform outputs
#   ./scripts/aws-deploy.sh deploy-k8s beta     # Apply kustomize manifests for environment
#   ./scripts/aws-deploy.sh build beta                    # Build, push, restart all images
#   ./scripts/aws-deploy.sh build production backend      # Build only backend
#   ./scripts/aws-deploy.sh build beta frontend backend   # Build multiple images
#   ./scripts/aws-deploy.sh build beta --cached           # Build with Docker cache
#   ./scripts/aws-deploy.sh build beta backend --cached   # Build only backend with cache
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

# Parse arguments
COMMAND="${1:-}"
ENVIRONMENT="${2:-}"

# Validate command
case "$COMMAND" in
    init|plan|apply|destroy|output|state|all|deploy-k8s|build)
        ;;
    *)
        error "Invalid command: $COMMAND\n\nUsage: ./scripts/aws-deploy.sh {init|plan|apply|all|destroy|output|state|deploy-k8s|build} {production|beta|shared}"
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
if [ "$ENVIRONMENT" = "shared" ]; then
    TF_DIR="$PROJECT_ROOT/k8s/terraform/shared"
    BACKEND_CONFIG="backend.hcl"
    TFVARS_FILE="terraform.shared.tfvars"
else
    TF_DIR="$PROJECT_ROOT/k8s/terraform/aws"
    BACKEND_CONFIG="backend-${ENVIRONMENT}.hcl"
    TFVARS_FILE="terraform.${ENVIRONMENT}.tfvars"
fi

# Only cd to terraform dir for terraform commands
if [ "$COMMAND" != "deploy-k8s" ] && [ "$COMMAND" != "build" ]; then
    cd "$TF_DIR"
fi

# Skip terraform file checks for commands that don't use terraform
if [ "$COMMAND" != "deploy-k8s" ] && [ "$COMMAND" != "build" ]; then
    # Check if backend config exists
    if [ ! -f "$BACKEND_CONFIG" ]; then
        error "Backend config not found: $TF_DIR/$BACKEND_CONFIG"
    fi
fi

# Check if tfvars file exists (except for state/output/deploy-k8s commands)
if [ "$COMMAND" != "state" ] && [ "$COMMAND" != "output" ] && [ "$COMMAND" != "deploy-k8s" ] && [ "$COMMAND" != "build" ]; then
    if [ ! -f "$TFVARS_FILE" ]; then
        warning "tfvars file not found: $TFVARS_FILE"
        info "Download from AWS Secrets Manager with:"
        info "  ./scripts/terraform/secrets.sh download $ENVIRONMENT"
        error "Missing tfvars file"
    fi
fi

# Verify correct backend is loaded (skip for init, all, and deploy-k8s which don't need terraform)
if [ "$COMMAND" != "init" ] && [ "$COMMAND" != "all" ] && [ "$COMMAND" != "deploy-k8s" ] && [ "$COMMAND" != "build" ]; then
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

# Display environment info (build command shows its own summary)
if [ "$COMMAND" != "build" ]; then
    info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    info "Environment: $ENVIRONMENT"
    info "Command:     $COMMAND"
    info "Backend:     $BACKEND_CONFIG"
    info "Terraform:   $TF_DIR"
    if [ "$COMMAND" != "state" ] && [ "$COMMAND" != "output" ] && [ "$COMMAND" != "deploy-k8s" ]; then
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
        KUSTOMIZE_DIR="$PROJECT_ROOT/k8s/overlays/aws-${ENVIRONMENT}"

        if [ ! -d "$KUSTOMIZE_DIR" ]; then
            error "Kustomize overlay not found: $KUSTOMIZE_DIR"
        fi

        # Auto-switch kubectl context to the correct EKS cluster
        CLUSTER_NAME="tesslate-${ENVIRONMENT}-eks"
        CURRENT_CONTEXT=$(kubectl config current-context 2>/dev/null || echo "")

        if [[ "$CURRENT_CONTEXT" != *"$CLUSTER_NAME"* ]]; then
            info "Switching kubectl context to $CLUSTER_NAME..."
            aws eks update-kubeconfig --region us-east-1 --name "$CLUSTER_NAME" 2>/dev/null \
                || error "Failed to update kubeconfig for $CLUSTER_NAME. Check AWS credentials."
            success "✓ kubectl context set to $CLUSTER_NAME"
        fi

        # Verify cluster is reachable
        if ! kubectl cluster-info --request-timeout=10s >/dev/null 2>&1; then
            error "Cannot reach cluster $CLUSTER_NAME. Check AWS credentials and VPN."
        fi

        info "Deploying kustomize manifests from aws-${ENVIRONMENT}..."
        kubectl apply -k "$KUSTOMIZE_DIR"

        success "✓ Kustomize manifests applied for $ENVIRONMENT"
        echo
        info "Verify with: kubectl get pods -n tesslate"
        ;;

    build)
        # Build is only for production/beta (shared only manages ECR repos)
        if [ "$ENVIRONMENT" = "shared" ]; then
            error "Build is not available for shared environment (shared only manages ECR repos)"
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

        # Image definitions
        declare -A DOCKERFILES=(
            [backend]="orchestrator/Dockerfile"
            [frontend]="app/Dockerfile.prod"
            [devserver]="orchestrator/Dockerfile.devserver"
        )
        declare -A BUILD_CONTEXTS=(
            [backend]="orchestrator/"
            [frontend]="app/"
            [devserver]="orchestrator/"
        )
        declare -A K8S_LABELS=(
            [backend]="app=tesslate-backend"
            [frontend]="app=tesslate-frontend"
        )

        # Validate image names
        for img in $IMAGES; do
            case "$img" in
                backend|frontend|devserver) ;;
                *) error "Unknown image: $img. Valid: backend, frontend, devserver" ;;
            esac
        done

        # Summary
        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        info "Environment: $ENVIRONMENT"
        info "Command:     build"
        info "Images:      $IMAGES"
        info "Registry:    $ECR_REGISTRY"
        info "Tag:         $ENVIRONMENT"
        if [ "$USE_CACHE" = true ]; then
            info "Cache:       enabled"
        else
            info "Cache:       disabled (use --cached to enable)"
        fi
        info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo

        # ECR Login
        info "Logging into ECR..."
        aws ecr get-login-password --region us-east-1 \
            | docker login --username AWS --password-stdin "$ECR_REGISTRY" 2>/dev/null
        success "✓ ECR login successful"
        echo

        # Build & Push
        for img in $IMAGES; do
            FULL_TAG="${ECR_REGISTRY}/tesslate-${img}:${ENVIRONMENT}"
            DOCKERFILE="${DOCKERFILES[$img]}"
            CONTEXT="${BUILD_CONTEXTS[$img]}"

            CACHE_FLAG="--no-cache"
            if [ "$USE_CACHE" = true ]; then
                CACHE_FLAG=""
            fi

            info "[$img] Building ${FULL_TAG}..."
            docker build $CACHE_FLAG -t "$FULL_TAG" -f "$PROJECT_ROOT/$DOCKERFILE" "$PROJECT_ROOT/$CONTEXT"
            success "[$img] ✓ Build complete"

            info "[$img] Pushing..."
            docker push "$FULL_TAG"
            success "[$img] ✓ Push complete"
            echo
        done

        # Switch kubectl context
        CLUSTER_NAME="tesslate-${ENVIRONMENT}-eks"
        CURRENT_CONTEXT=$(kubectl config current-context 2>/dev/null || echo "")

        if [[ "$CURRENT_CONTEXT" != *"$CLUSTER_NAME"* ]]; then
            info "Switching kubectl context to $CLUSTER_NAME..."
            aws eks update-kubeconfig --region us-east-1 --name "$CLUSTER_NAME" --alias "$CLUSTER_NAME" >/dev/null 2>&1 \
                || error "Failed to switch kubectl context. Does cluster '$CLUSTER_NAME' exist?"
            success "✓ kubectl context set to $CLUSTER_NAME"
        fi
        echo

        # Restart pods
        info "Restarting pods on $CLUSTER_NAME..."
        for img in $IMAGES; do
            LABEL="${K8S_LABELS[$img]:-}"
            if [ -n "$LABEL" ]; then
                info "[$img] Deleting pod..."
                kubectl delete pod -n tesslate -l "$LABEL" 2>/dev/null || true
            fi
        done

        # Wait for rollouts in parallel
        ROLLOUT_PIDS=()
        ROLLOUT_IMGS=()
        for img in $IMAGES; do
            LABEL="${K8S_LABELS[$img]:-}"
            if [ -n "$LABEL" ]; then
                info "[$img] Waiting for rollout..."
                kubectl rollout status "deployment/tesslate-${img}" -n tesslate --timeout=120s &
                ROLLOUT_PIDS+=($!)
                ROLLOUT_IMGS+=("$img")
            fi
        done

        # Collect results
        FAILED=0
        for i in "${!ROLLOUT_PIDS[@]}"; do
            if wait "${ROLLOUT_PIDS[$i]}"; then
                success "[${ROLLOUT_IMGS[$i]}] ✓ Ready"
            else
                error "[${ROLLOUT_IMGS[$i]}] ✗ Rollout failed"
                FAILED=1
            fi
        done

        if [ "$FAILED" -ne 0 ]; then
            error "One or more rollouts failed. Check pod status with: kubectl get pods -n tesslate"
        fi
        echo

        # Verify
        info "Verifying deployment..."
        kubectl get pods -n tesslate -o wide | grep -v cleanup
        echo
        success "✓ Build and deploy complete for $ENVIRONMENT!"
        ;;

    all)
        info "Running full deployment for $ENVIRONMENT environment..."
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
