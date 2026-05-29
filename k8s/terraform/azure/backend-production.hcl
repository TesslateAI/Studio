# =============================================================================
# Terraform Backend Configuration - Azure Production Environment
# =============================================================================
# Usage: terraform init -backend-config=backend-production.hcl
# =============================================================================

resource_group_name  = "tesslate-tfstate-rg"
storage_account_name = "tesslatetfstate111e00"
container_name       = "tfstate"
key                  = "production/terraform.tfstate"
