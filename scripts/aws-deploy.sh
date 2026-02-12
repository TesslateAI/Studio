#!/bin/bash
# =============================================================================
# Terraform Deployment Helper Script for AWS EKS
# =============================================================================
# Manages environment-specific Terraform deployments with proper backend config
#
# Usage:
#   ./scripts/aws-deploy.sh init production    # Initialize production backend
#   ./scripts/aws-deploy.sh plan production     # Plan production changes
#   ./scripts/aws-deploy.sh apply production    # Apply production changes
#   ./scripts/aws-deploy.sh all production      # Run init → plan → apply (full deployment)
#   ./scripts/aws-deploy.sh destroy production  # Destroy production resources
#   ./scripts/aws-deploy.sh output beta         # Show terraform outputs
#   ./scripts/aws-deploy.sh deploy-k8s beta     # Apply kustomize manifests for environment
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TF_DIR="$PROJECT_ROOT/k8s/terraform/aws"

cd "$TF_DIR"

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
    init|plan|apply|destroy|output|state|all|deploy-k8s)
        ;;
    *)
        error "Invalid command: $COMMAND\n\nUsage: ./scripts/aws-deploy.sh {init|plan|apply|all|destroy|output|state|deploy-k8s} {production|beta}"
        ;;
esac

# Validate environment
if [ -z "$ENVIRONMENT" ]; then
    error "Environment not specified.\n\nUsage: ./scripts/aws-deploy.sh $COMMAND {production|beta}"
fi

case "$ENVIRONMENT" in
    production|beta)
        ;;
    *)
        error "Invalid environment: $ENVIRONMENT. Use 'production' or 'beta'"
        ;;
esac

# Set environment-specific files
BACKEND_CONFIG="backend-${ENVIRONMENT}.hcl"
TFVARS_FILE="terraform.${ENVIRONMENT}.tfvars"

# Skip terraform file checks for commands that don't use terraform
if [ "$COMMAND" != "deploy-k8s" ]; then
    # Check if backend config exists
    if [ ! -f "$BACKEND_CONFIG" ]; then
        error "Backend config not found: $TF_DIR/$BACKEND_CONFIG"
    fi
fi

# Check if tfvars file exists (except for state/output/deploy-k8s commands)
if [ "$COMMAND" != "state" ] && [ "$COMMAND" != "output" ] && [ "$COMMAND" != "deploy-k8s" ]; then
    if [ ! -f "$TFVARS_FILE" ]; then
        warning "tfvars file not found: $TFVARS_FILE"
        info "Pull from AWS Secrets Manager with:"
        info "  ./scripts/terraform/sync_tfvars.sh pull $ENVIRONMENT"
        error "Missing tfvars file"
    fi
fi

# Verify correct backend is loaded (skip for init, all, and deploy-k8s which don't need terraform)
if [ "$COMMAND" != "init" ] && [ "$COMMAND" != "all" ] && [ "$COMMAND" != "deploy-k8s" ]; then
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

# Display environment info
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

        info "Deploying kustomize manifests from aws-${ENVIRONMENT}..."
        kubectl apply -k "$KUSTOMIZE_DIR"

        success "✓ Kustomize manifests applied for $ENVIRONMENT"
        echo
        info "Verify with: kubectl get pods -n tesslate"
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
