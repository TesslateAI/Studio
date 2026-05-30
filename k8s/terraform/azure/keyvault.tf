# =============================================================================
# Azure Key Vault — terraform variables + tfvars-backup storage
# =============================================================================
# Mirrors how the AWS stack uses AWS Secrets Manager via `scripts/terraform/
# secrets.sh`. The KV is created here so future operators (or a fresh
# machine) can pull the tfvars file via `scripts/terraform/azure-secrets.sh
# download <env>` instead of needing to copy it out of band.
#
# RBAC mode (not access-policy mode): permissions are managed via Azure RBAC
# role assignments on the vault scope. Equivalent to IAM on Secrets Manager.
#
# What's stored here:
#   - <AWS_IAM_USER>-{env}    — the full tfvars file as one secret
#                                   (uploaded by scripts/terraform/azure-secrets.sh)
#
# The tfvars file itself contains the Cloudflare token, Postgres password,
# app secret, internal API secret, LiteLLM keys, OAuth client secrets, etc.
# Treating it as one opaque secret matches how the AWS Secrets Manager path
# works and keeps the upload/download flow simple.
# =============================================================================

locals {
  # KV names cap at 24 chars. `tesslate-` (9) + truncated env (4)
  # + `-` (1) + 8-char random hex (8) = 22. Truncation:
  # "beta" → "beta", "production" → "prod".
  kv_env_short = substr(var.environment, 0, 4)
}

resource "azurerm_key_vault" "this" {
  # KV names must be globally unique, 3-24 chars, alphanumeric + dashes,
  # start with a letter. Reusing random_id.suffix.hex keeps it stable.
  name                = "${var.project_name}-${local.kv_env_short}-${random_id.suffix.hex}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  tenant_id           = data.azurerm_client_config.current.tenant_id

  sku_name = "standard"

  # RBAC mode — permission via azurerm_role_assignment, not access_policy.
  # AAD groups get Key Vault Secrets Officer / Reader / etc.
  enable_rbac_authorization = true

  # Soft-delete is mandatory and on by default in current API versions;
  # purge protection is opt-in. We turn it on for prod (real damage if the
  # vault is purged) and leave it off in beta so destroys work cleanly.
  soft_delete_retention_days = 30
  purge_protection_enabled   = var.environment == "production"

  # Network ACLs — default-allow with Azure services bypass. Tighten later
  # by adding `ip_rules` / `virtual_network_subnet_ids` once the operator
  # set is stable.
  network_acls {
    default_action = "Allow"
    bypass         = "AzureServices"
  }

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# Operator access — anyone in `var.kv_secrets_officer_object_ids` (AAD user
# or group object IDs) can create/read/update/delete secrets in this vault.
# Use this for the engineers driving `azure-secrets.sh download/upload`.
# -----------------------------------------------------------------------------
resource "azurerm_role_assignment" "kv_secrets_officer" {
  for_each = toset(var.kv_secrets_officer_object_ids)

  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = each.key
}

# -----------------------------------------------------------------------------
# AKS admin group — Key Vault Secrets Officer by default, so cluster admins
# can rotate secrets without an extra role assignment step. Mirrors the AWS
# pattern where team_admin gets full secrets:* permissions on
# tesslate/terraform/*.
# -----------------------------------------------------------------------------
resource "azurerm_role_assignment" "kv_admin_secrets_officer" {
  for_each = toset(var.aks_admin_group_object_ids)

  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = each.key
}
