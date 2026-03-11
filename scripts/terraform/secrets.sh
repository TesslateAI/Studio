#!/bin/bash
# =============================================================================
# Terraform Secrets - Manage tfvars in AWS Secrets Manager
# =============================================================================
# Upload, download, and view terraform.{env}.tfvars files in AWS Secrets Manager.
# Secrets are stored as raw tfvars file content.
#
# Usage:
#   ./scripts/terraform/secrets.sh download production
#   ./scripts/terraform/secrets.sh upload production
#   ./scripts/terraform/secrets.sh view production
#
# Short form (defaults to view):
#   ./scripts/terraform/secrets.sh production
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

error() {
  echo -e "${RED}Error: $1${NC}" >&2
  exit 1
}

success() {
  echo -e "${GREEN}$1${NC}"
}

info() {
  echo -e "${BLUE}$1${NC}"
}

warning() {
  echo -e "${YELLOW}$1${NC}"
}

# Parse arguments
FIRST_ARG="${1:-}"
SECOND_ARG="${2:-}"

# Determine command and environment
# If first arg is a command, use it; otherwise default to download
if [[ "$FIRST_ARG" =~ ^(upload|download|view)$ ]]; then
  COMMAND="$FIRST_ARG"
  ENVIRONMENT="$SECOND_ARG"
else
  # First arg is environment, default to view
  COMMAND="view"
  ENVIRONMENT="$FIRST_ARG"
fi

# Show usage if no arguments
if [ -z "$ENVIRONMENT" ]; then
  echo "Usage: $0 [command] {production|beta|shared}"
  echo ""
  echo "Commands:"
  echo "  view      - View tfvars content from AWS (default)"
  echo "  download  - Download tfvars from AWS to local file"
  echo "  upload    - Upload local tfvars to AWS Secrets Manager"
  echo ""
  echo "Examples:"
  echo "  $0 production                 # View (short form)"
  echo "  $0 view production            # View content in AWS"
  echo "  $0 download production        # Download to local file"
  echo "  $0 upload production          # Upload local file to AWS"
  echo "  $0 shared                     # View shared stack tfvars"
  exit 1
fi

# Validate environment
case "$ENVIRONMENT" in
  production|beta|shared) ;;
  *)
    error "Invalid environment: $ENVIRONMENT. Use 'production', 'beta', or 'shared'"
    ;;
esac

# Set paths and names based on environment
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "$ENVIRONMENT" in
  shared)
    TFVARS_FILE="$SCRIPT_DIR/../../k8s/terraform/shared/terraform.shared.tfvars"
    ;;
  *)
    TFVARS_FILE="$SCRIPT_DIR/../../k8s/terraform/aws/terraform.${ENVIRONMENT}.tfvars"
    ;;
esac
SECRET_NAME="tesslate/terraform/${ENVIRONMENT}"

# Check dependencies
if ! command -v aws &> /dev/null; then
  error "AWS CLI not installed\nInstall from: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
fi

# Check AWS credentials
if ! aws sts get-caller-identity &> /dev/null; then
  error "AWS credentials not configured\nRun: aws configure"
fi

# =============================================================================
# Command: DOWNLOAD - Download tfvars from AWS to local file
# =============================================================================
cmd_download() {
  info "Downloading terraform.${ENVIRONMENT}.tfvars from AWS Secrets Manager..."

  # Check if local file exists
  if [ -f "$TFVARS_FILE" ]; then
    warning "⚠️  Local file already exists: $TFVARS_FILE"
    echo
    warning "This will OVERWRITE the local file."
    echo
    read -p "Continue? (yes/no): " -r
    echo
    if [[ ! $REPLY == "yes" ]]; then
      info "Cancelled."
      exit 0
    fi
  fi

  # Fetch secret from AWS
  TFVARS_CONTENT=$(aws secretsmanager get-secret-value \
    --secret-id "$SECRET_NAME" \
    --query SecretString \
    --output text 2>&1) || {
    echo ""
    error "Failed to fetch secret: $SECRET_NAME\n\nSecret may not exist yet. Upload with:\n  $0 upload $ENVIRONMENT"
  }

  # Create directory if it doesn't exist
  TFVARS_DIR=$(dirname "$TFVARS_FILE")
  mkdir -p "$TFVARS_DIR"

  # Write to local file
  echo "$TFVARS_CONTENT" > "$TFVARS_FILE"

  # Count variables
  VAR_COUNT=$(grep -c '^[a-zA-Z_]' "$TFVARS_FILE" || echo "0")

  echo
  success "✓ Downloaded terraform.${ENVIRONMENT}.tfvars from AWS"
  info "  Location: $TFVARS_FILE"
  info "  Variables: $VAR_COUNT"
  echo
  TF_DIR_HINT=$(dirname "$TFVARS_FILE" | sed "s|.*/k8s/|k8s/|")
  info "Ready to use with:"
  info "  cd $TF_DIR_HINT"
  info "  terraform plan -var-file=\"terraform.${ENVIRONMENT}.tfvars\""
  echo
}

# =============================================================================
# Command: UPLOAD - Upload local tfvars file to AWS
# =============================================================================
cmd_upload() {
  # Check if tfvars file exists
  if [ ! -f "$TFVARS_FILE" ]; then
    error "tfvars file not found: $TFVARS_FILE\n\nCreate it first or download from AWS with:\n  $0 download $ENVIRONMENT"
  fi

  info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  info "Uploading terraform.${ENVIRONMENT}.tfvars to AWS Secrets Manager"
  info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo
  info "Environment:  $ENVIRONMENT"
  info "Source file:  $TFVARS_FILE"
  info "AWS Secret:   $SECRET_NAME"
  echo

  # Read tfvars file content
  TFVARS_CONTENT=$(cat "$TFVARS_FILE")

  # Count variables
  VAR_COUNT=$(echo "$TFVARS_CONTENT" | grep -c '^[a-zA-Z_]' || echo "0")
  success "✓ Read $VAR_COUNT variables from local file"
  echo

  # Check if secret already exists
  info "Checking if secret already exists in AWS..."
  if aws secretsmanager describe-secret --secret-id "$SECRET_NAME" &> /dev/null; then
    warning "⚠️  Secret already exists: $SECRET_NAME"
    echo
    warning "This will OVERWRITE the existing secret in AWS Secrets Manager."
    echo
    read -p "Continue? (yes/no): " -r
    echo
    if [[ ! $REPLY == "yes" ]]; then
      info "Cancelled."
      exit 0
    fi

    info "Updating existing secret..."
    aws secretsmanager put-secret-value \
      --secret-id "$SECRET_NAME" \
      --secret-string "$TFVARS_CONTENT" > /dev/null

    success "✓ Secret updated in AWS Secrets Manager"
  else
    info "Creating new secret in AWS..."
    aws secretsmanager create-secret \
      --name "$SECRET_NAME" \
      --description "Terraform variables for Tesslate Studio ${ENVIRONMENT} environment" \
      --secret-string "$TFVARS_CONTENT" > /dev/null

    success "✓ Secret created in AWS Secrets Manager"
  fi

  echo
  info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  success "Upload complete!"
  info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo
  info "Team members can now download with:"
  info "  $0 download $ENVIRONMENT"
  echo
}

# =============================================================================
# Command: VIEW - Display tfvars content from AWS
# =============================================================================
cmd_view() {
  info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  info "Viewing terraform.${ENVIRONMENT}.tfvars from AWS Secrets Manager"
  info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo
  info "Environment:  $ENVIRONMENT"
  info "AWS Secret:   $SECRET_NAME"
  echo

  # Fetch secret
  info "Fetching secret from AWS..."
  TFVARS_CONTENT=$(aws secretsmanager get-secret-value \
    --secret-id "$SECRET_NAME" \
    --query SecretString \
    --output text 2>&1) || {
    error "Failed to fetch secret: $SECRET_NAME\n\nSecret may not exist yet. Upload with:\n  $0 upload $ENVIRONMENT"
  }

  # Display content
  echo
  success "Content from AWS Secrets Manager:"
  echo
  echo "----------------------------------------"
  echo "$TFVARS_CONTENT"
  echo "----------------------------------------"
  echo

  # Count variables
  VAR_COUNT=$(echo "$TFVARS_CONTENT" | grep -c '^[a-zA-Z_]' || echo "0")
  info "Total: $VAR_COUNT variables"
  echo
}

# =============================================================================
# Route to appropriate command
# =============================================================================
case "$COMMAND" in
  download)
    cmd_download
    ;;
  upload)
    cmd_upload
    ;;
  view)
    cmd_view
    ;;
esac
