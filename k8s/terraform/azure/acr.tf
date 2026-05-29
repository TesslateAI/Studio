# =============================================================================
# Azure Container Registry (ACR) for OpenSail
# =============================================================================
# Single ACR holds all environment images — different tags (`production`,
# `beta`) push to the same repositories. Pull-through cache rules mirror
# common public images so AKS nodes don't pull straight from quay.io / dockerhub.
#
# Mirrors k8s/terraform/shared/ecr.tf in the AWS stack — except ACR can live
# in the per-environment stack on Azure because ACR names are cheaper to
# scope (no separate "shared" terraform stack required for ACR alone).
# =============================================================================

resource "azurerm_container_registry" "this" {
  name                = local.acr_name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location

  # Premium gives us geo-replication, content trust, customer-managed keys,
  # pull-through cache, retention policies, and trust policies. Production
  # wants Premium; beta saves by running on Standard.
  sku           = var.environment == "production" ? "Premium" : "Standard"
  admin_enabled = false # ACR admin user disabled — all auth via AAD / Workload Identity

  # Retention + trust policies are Premium-only. Skip on Standard so beta
  # plans cleanly. Untagged manifest cleanup on Standard happens via the
  # `Microsoft.ContainerRegistry/registries/runs` task (or just left to
  # bound storage growth).
  dynamic "retention_policy" {
    for_each = var.environment == "production" ? [1] : []
    content {
      enabled = true
      days    = 7
    }
  }

  dynamic "trust_policy" {
    for_each = var.environment == "production" ? [1] : []
    content {
      enabled = true
    }
  }

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# Pull-through cache: quay.io mirror for common public images.
# AKS nodes pulling `nginx`, `postgres`, etc. transparently get them via ACR
# instead of hitting Quay directly. Matches the AWS ECR pull-through rule.
# Premium SKU only — no-op on Standard.
# -----------------------------------------------------------------------------
resource "azurerm_container_registry_cache_rule" "quay_mirror" {
  count = var.environment == "production" ? 1 : 0

  name                  = "quay-mirror"
  container_registry_id = azurerm_container_registry.this.id
  source_repo           = "quay.io/*"
  target_repo           = "quay/*"
}
