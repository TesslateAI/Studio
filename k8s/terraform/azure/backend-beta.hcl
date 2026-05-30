# =============================================================================
# Terraform Backend Configuration - Azure Beta Environment
# =============================================================================
# Usage: terraform init -backend-config=backend-beta.hcl
#
# The backing Storage Account + Container must be pre-created out-of-band
# (chicken-and-egg) — see README.md for the bootstrap commands.
# =============================================================================

resource_group_name  = "tesslate-tfstate-rg"
storage_account_name = "tesslatetfstate111e00"
container_name       = "tfstate"
key                  = "beta/terraform.tfstate"
