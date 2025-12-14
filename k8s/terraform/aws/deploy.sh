#!/bin/bash
# =============================================================================
# Tesslate Studio - AWS EKS Deployment Script
# =============================================================================
# This script automates the deployment of Tesslate Studio on AWS EKS
# Usage: ./deploy.sh [init|plan|apply|build|push|deploy|all|destroy]
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        log_error "AWS CLI not found. Please install it first."
        exit 1
    fi

    # Check Terraform
    if ! command -v terraform &> /dev/null; then
        log_error "Terraform not found. Please install it first."
        exit 1
    fi

    # Check kubectl
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl not found. Please install it first."
        exit 1
    fi

    # Check Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker not found. Please install it first."
        exit 1
    fi

    # Check terraform.tfvars exists
    if [ ! -f "$SCRIPT_DIR/terraform.tfvars" ]; then
        log_error "terraform.tfvars not found. Please copy terraform.tfvars.example and fill in your values."
        exit 1
    fi

    log_success "All prerequisites met!"
}

terraform_init() {
    log_info "Initializing Terraform..."
    cd "$SCRIPT_DIR"
    terraform init
    log_success "Terraform initialized!"
}

terraform_plan() {
    log_info "Planning Terraform changes..."
    cd "$SCRIPT_DIR"
    terraform plan -out=tfplan
    log_success "Plan complete! Review the changes above."
}

terraform_apply() {
    log_info "Applying Terraform configuration..."
    cd "$SCRIPT_DIR"

    if [ ! -f "tfplan" ]; then
        log_warning "No plan file found. Running plan first..."
        terraform_plan
    fi

    terraform apply tfplan
    log_success "Infrastructure deployed!"

    # Configure kubectl
    log_info "Configuring kubectl..."
    eval "$(terraform output -raw configure_kubectl_command)"
    log_success "kubectl configured!"
}

build_images() {
    log_info "Building Docker images..."
    cd "$PROJECT_ROOT"

    # Get ECR URLs from Terraform
    cd "$SCRIPT_DIR"
    BACKEND_REPO=$(terraform output -raw ecr_backend_repository_url)
    FRONTEND_REPO=$(terraform output -raw ecr_frontend_repository_url)
    DEVSERVER_REPO=$(terraform output -raw ecr_devserver_repository_url)

    cd "$PROJECT_ROOT"

    log_info "Building backend..."
    docker build -t "$BACKEND_REPO:latest" -f orchestrator/Dockerfile orchestrator/

    log_info "Building frontend..."
    docker build -t "$FRONTEND_REPO:latest" -f app/Dockerfile.prod app/

    log_info "Building devserver..."
    docker build -t "$DEVSERVER_REPO:latest" -f orchestrator/Dockerfile.devserver orchestrator/

    log_success "All images built!"
}

push_images() {
    log_info "Pushing Docker images to ECR..."
    cd "$SCRIPT_DIR"

    # Login to ECR
    log_info "Logging in to ECR..."
    eval "$(terraform output -raw ecr_login_command)"

    BACKEND_REPO=$(terraform output -raw ecr_backend_repository_url)
    FRONTEND_REPO=$(terraform output -raw ecr_frontend_repository_url)
    DEVSERVER_REPO=$(terraform output -raw ecr_devserver_repository_url)

    log_info "Pushing backend..."
    docker push "$BACKEND_REPO:latest"

    log_info "Pushing frontend..."
    docker push "$FRONTEND_REPO:latest"

    log_info "Pushing devserver..."
    docker push "$DEVSERVER_REPO:latest"

    log_success "All images pushed to ECR!"
}

update_kustomization() {
    log_info "Updating kustomization with ECR URLs..."
    cd "$SCRIPT_DIR"

    BACKEND_REPO=$(terraform output -raw ecr_backend_repository_url)
    FRONTEND_REPO=$(terraform output -raw ecr_frontend_repository_url)
    DEVSERVER_REPO=$(terraform output -raw ecr_devserver_repository_url)

    KUSTOMIZATION_FILE="$PROJECT_ROOT/k8s/overlays/aws/kustomization.yaml"

    # Extract account ID and region from ECR URL
    ECR_REGISTRY=$(echo "$BACKEND_REPO" | cut -d'/' -f1)

    # Update kustomization.yaml
    sed -i.bak "s|ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/tesslate-backend|$BACKEND_REPO|g" "$KUSTOMIZATION_FILE"
    sed -i.bak "s|ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/tesslate-frontend|$FRONTEND_REPO|g" "$KUSTOMIZATION_FILE"
    sed -i.bak "s|ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/tesslate-devserver|$DEVSERVER_REPO|g" "$KUSTOMIZATION_FILE"

    rm -f "$KUSTOMIZATION_FILE.bak"

    log_success "Kustomization updated!"
}

deploy_app() {
    log_info "Deploying Tesslate application to EKS..."

    # Update kustomization with ECR URLs
    update_kustomization

    # Apply Kubernetes manifests
    kubectl apply -k "$PROJECT_ROOT/k8s/overlays/aws"

    log_info "Waiting for deployments to be ready..."
    kubectl rollout status deployment/tesslate-backend -n tesslate --timeout=300s
    kubectl rollout status deployment/tesslate-frontend -n tesslate --timeout=300s

    log_success "Application deployed!"

    # Show status
    echo ""
    log_info "Deployment Status:"
    kubectl get pods -n tesslate
    echo ""
    kubectl get ingress -n tesslate
    echo ""

    # Get NLB DNS name
    NLB_DNS=$(kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "pending")

    echo ""
    log_info "==================== NEXT STEPS ===================="
    echo ""
    echo "1. Configure Cloudflare DNS:"
    echo "   - Add CNAME record: saipriya.org → $NLB_DNS"
    echo "   - Add CNAME record: *.saipriya.org → $NLB_DNS"
    echo ""
    echo "2. Set Cloudflare SSL/TLS mode to 'Full (strict)'"
    echo ""
    echo "3. Wait for certificate to be issued (check with):"
    echo "   kubectl get certificate -n tesslate"
    echo ""
    echo "4. Access your application at: https://saipriya.org"
    echo ""
    log_info "===================================================="
}

destroy() {
    log_warning "This will destroy ALL infrastructure including data!"
    read -p "Are you sure? (yes/no): " confirm

    if [ "$confirm" != "yes" ]; then
        log_info "Aborted."
        exit 0
    fi

    log_info "Deleting user project namespaces..."
    kubectl get ns | grep proj- | awk '{print $1}' | xargs -r kubectl delete ns --timeout=60s || true

    log_info "Destroying Terraform resources..."
    cd "$SCRIPT_DIR"
    terraform destroy

    log_success "Infrastructure destroyed!"
}

show_help() {
    echo "Tesslate Studio - AWS EKS Deployment Script"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  init      Initialize Terraform"
    echo "  plan      Plan Terraform changes"
    echo "  apply     Apply Terraform configuration"
    echo "  build     Build Docker images"
    echo "  push      Push images to ECR"
    echo "  deploy    Deploy application to EKS"
    echo "  all       Run all steps (init, plan, apply, build, push, deploy)"
    echo "  destroy   Destroy all infrastructure"
    echo "  help      Show this help message"
    echo ""
}

# Main
case "${1:-help}" in
    init)
        check_prerequisites
        terraform_init
        ;;
    plan)
        check_prerequisites
        terraform_plan
        ;;
    apply)
        check_prerequisites
        terraform_apply
        ;;
    build)
        check_prerequisites
        build_images
        ;;
    push)
        check_prerequisites
        push_images
        ;;
    deploy)
        check_prerequisites
        deploy_app
        ;;
    all)
        check_prerequisites
        terraform_init
        terraform_plan
        terraform_apply
        build_images
        push_images
        deploy_app
        ;;
    destroy)
        destroy
        ;;
    help|*)
        show_help
        ;;
esac
