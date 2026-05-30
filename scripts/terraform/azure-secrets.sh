#!/bin/bash
# =============================================================================
# Azure Terraform Secrets — Manage tfvars in Azure Key Vault
# =============================================================================
# Upload, download, and view terraform.{env}.tfvars in Azure Key Vault.
# Mirrors scripts/terraform/secrets.sh (the AWS Secrets Manager equivalent).
#
# Usage:
#   ./scripts/terraform/azure-secrets.sh download beta
#   ./scripts/terraform/azure-secrets.sh upload beta
#   ./scripts/terraform/azure-secrets.sh view beta
#   ./scripts/terraform/azure-secrets.sh versions beta
#
# Short form (defaults to view):
#   ./scripts/terraform/azure-secrets.sh beta
#
# The Key Vault is created by k8s/terraform/azure/keyvault.tf. The vault
# name is read from `terraform output -raw key_vault_name`; the secret name
# is always `<AWS_IAM_USER>-{env}` (one secret per environment, raw
# tfvars file contents).
#
# Auth: caller must be a Key Vault Secrets Officer on the vault. Engineers
# get this by being in the AKS admin AAD group OR by being listed in
# var.kv_secrets_officer_object_ids in tfvars.
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TF_DIR="$PROJECT_ROOT/k8s/terraform/azure"

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

# Parse args: support both `<env>` (defaults to view) and `<action> <env>`
ACTION="${1:-}"
ENVIRONMENT="${2:-}"

if [ -z "$ENVIRONMENT" ] && [ -n "$ACTION" ]; then
    # Single-arg form treats the arg as environment, defaults to view
    case "$ACTION" in
        production|beta)
            ENVIRONMENT="$ACTION"
            ACTION="view"
            ;;
        *)
            error "Invalid arg: '$ACTION'. Usage: ./scripts/terraform/azure-secrets.sh {download|upload|view|versions} {production|beta}"
            ;;
    esac
fi

case "$ACTION" in
    download|upload|view|versions) ;;
    *)
        error "Invalid action: '$ACTION'. Use download|upload|view|versions."
        ;;
esac

case "$ENVIRONMENT" in
    production|beta) ;;
    *)
        error "Invalid environment: '$ENVIRONMENT'. Use production or beta."
        ;;
esac

TFVARS_FILE="$TF_DIR/terraform.${ENVIRONMENT}.tfvars"
SECRET_NAME="<AWS_IAM_USER>-${ENVIRONMENT}"

# ----------------------------------------------------------------------------
# Resolve Key Vault name from terraform output. Falls back to the
# documented naming pattern if state isn't available locally.
# ----------------------------------------------------------------------------
resolve_vault_name() {
    if VAULT=$(terraform -chdir="$TF_DIR" output -raw key_vault_name 2>/dev/null); then
        if [ -n "$VAULT" ]; then
            echo "$VAULT"
            return 0
        fi
    fi

    # State isn't initialized for this env's backend — caller can override
    # via $AZURE_KEY_VAULT_NAME. Fail loudly otherwise so they don't end up
    # uploading to the wrong vault.
    if [ -n "${AZURE_KEY_VAULT_NAME:-}" ]; then
        echo "$AZURE_KEY_VAULT_NAME"
        return 0
    fi

    error "Couldn't resolve Key Vault name. Run 'terraform -chdir=$TF_DIR init -backend-config=backend-${ENVIRONMENT}.hcl' first, or export AZURE_KEY_VAULT_NAME."
}

# ----------------------------------------------------------------------------
# Auth check — `az account show` must succeed before any KV op.
# ----------------------------------------------------------------------------
if ! az account show >/dev/null 2>&1; then
    error "Not logged into Azure. Run 'az login' first."
fi

VAULT_NAME=$(resolve_vault_name)

info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
info "Cloud:         Azure"
info "Action:        $ACTION"
info "Environment:   $ENVIRONMENT"
info "Key Vault:     $VAULT_NAME"
info "Secret:        $SECRET_NAME"
info "Local tfvars:  $TFVARS_FILE"
info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo

case "$ACTION" in
    download)
        if [ -f "$TFVARS_FILE" ]; then
            warning "$TFVARS_FILE already exists. Backing up to ${TFVARS_FILE}.bak before overwriting."
            cp "$TFVARS_FILE" "${TFVARS_FILE}.bak"
        fi
        info "Downloading $SECRET_NAME from $VAULT_NAME..."
        if ! az keyvault secret show \
                --vault-name "$VAULT_NAME" \
                --name "$SECRET_NAME" \
                --query value -o tsv > "$TFVARS_FILE" 2>/dev/null; then
            rm -f "$TFVARS_FILE"
            error "Failed to download $SECRET_NAME from $VAULT_NAME. Does the secret exist? Do you have Key Vault Secrets User on the vault?"
        fi
        chmod 600 "$TFVARS_FILE"
        success "✓ Downloaded to $TFVARS_FILE ($(wc -l < "$TFVARS_FILE") lines)"
        ;;

    upload)
        if [ ! -f "$TFVARS_FILE" ]; then
            error "$TFVARS_FILE doesn't exist. Nothing to upload."
        fi
        warning "About to upload $(wc -c < "$TFVARS_FILE") bytes from $TFVARS_FILE"
        warning "to secret '$SECRET_NAME' in vault '$VAULT_NAME'."
        warning "This creates a new version — previous versions are preserved."
        read -p "Continue? (yes/no): " -r
        echo
        if [[ ! $REPLY == "yes" ]]; then
            info "Cancelled."
            exit 0
        fi
        info "Uploading..."
        # --file path puts file contents verbatim into the secret value.
        # Content type tags the secret as a tfvars file for human inspection.
        if ! az keyvault secret set \
                --vault-name "$VAULT_NAME" \
                --name "$SECRET_NAME" \
                --file "$TFVARS_FILE" \
                --content-type "text/x-terraform-tfvars" \
                --only-show-errors >/dev/null 2>&1; then
            error "Upload failed. Do you have Key Vault Secrets Officer on $VAULT_NAME?"
        fi
        success "✓ Uploaded as new version of $SECRET_NAME"
        info "List versions with: ./scripts/terraform/azure-secrets.sh versions $ENVIRONMENT"
        ;;

    view)
        info "Showing current value of $SECRET_NAME (truncated to 30 lines):"
        echo
        az keyvault secret show \
            --vault-name "$VAULT_NAME" \
            --name "$SECRET_NAME" \
            --query value -o tsv 2>/dev/null | head -30
        echo
        info "(use 'download' to write the full file to $TFVARS_FILE)"
        ;;

    versions)
        info "Versions of $SECRET_NAME in $VAULT_NAME:"
        az keyvault secret list-versions \
            --vault-name "$VAULT_NAME" \
            --name "$SECRET_NAME" \
            --query "[].{enabled:attributes.enabled, created:attributes.created, version:id}" \
            -o table 2>/dev/null
        ;;
esac
