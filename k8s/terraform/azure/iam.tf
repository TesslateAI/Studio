# =============================================================================
# Identity & Access for OpenSail Azure
# =============================================================================
# Three User-Assigned Managed Identities, each federated to a specific K8s
# Service Account via AKS's OIDC issuer (Workload Identity). Mirrors the
# IRSA roles in aws/iam.tf:
#
#   tesslate-backend-uami  -> tesslate:tesslate-backend-sa
#     (read/write on projects + marketplace-bundles + btrfs-snapshots)
#   btrfs-csi-uami         -> kube-system:tesslate-btrfs-csi-node
#     (read/write on btrfs-snapshots)
#   volume-hub-uami        -> kube-system:tesslate-volume-hub
#     (read/write on btrfs-snapshots — same scope as btrfs-csi)
#
# Each UAMI also gets ACR Pull on the registry (kubelet identity covers most
# pulls, but explicit Pull lets pods that download from ACR via API succeed
# too — e.g. tesslate-marketplace fetching bundles via REST).
# =============================================================================

# -----------------------------------------------------------------------------
# Backend UAMI — used by tesslate-backend-sa
# -----------------------------------------------------------------------------
resource "azurerm_user_assigned_identity" "backend" {
  name                = "${local.cluster_name}-backend-uami"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location

  tags = local.common_tags
}

resource "azurerm_federated_identity_credential" "backend" {
  name                = "${local.cluster_name}-backend-fed"
  resource_group_name = azurerm_resource_group.this.name
  parent_id           = azurerm_user_assigned_identity.backend.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.this.oidc_issuer_url
  subject             = "system:serviceaccount:tesslate:tesslate-backend-sa"
}

resource "azurerm_role_assignment" "backend_projects_blob" {
  scope                = azurerm_storage_container.projects.resource_manager_id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.backend.principal_id
}

resource "azurerm_role_assignment" "backend_marketplace_blob" {
  scope                = azurerm_storage_container.marketplace_bundles.resource_manager_id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.backend.principal_id
}

resource "azurerm_role_assignment" "backend_btrfs_blob" {
  # Backend reads btrfs-snapshots manifests during project resume to verify
  # cache placement. Read-only is enough.
  scope                = azurerm_storage_container.btrfs_snapshots.resource_manager_id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_user_assigned_identity.backend.principal_id
}

resource "azurerm_role_assignment" "backend_acr_pull" {
  scope                = azurerm_container_registry.this.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.backend.principal_id
}

# -----------------------------------------------------------------------------
# btrfs CSI UAMI — used by kube-system:tesslate-btrfs-csi-node
# -----------------------------------------------------------------------------
resource "azurerm_user_assigned_identity" "btrfs_csi" {
  name                = "${local.cluster_name}-btrfs-csi-uami"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location

  tags = local.common_tags
}

resource "azurerm_federated_identity_credential" "btrfs_csi" {
  name                = "${local.cluster_name}-btrfs-csi-fed"
  resource_group_name = azurerm_resource_group.this.name
  parent_id           = azurerm_user_assigned_identity.btrfs_csi.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.this.oidc_issuer_url
  subject             = "system:serviceaccount:kube-system:tesslate-btrfs-csi-node"
}

resource "azurerm_role_assignment" "btrfs_csi_blob" {
  scope                = azurerm_storage_container.btrfs_snapshots.resource_manager_id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.btrfs_csi.principal_id
}

# -----------------------------------------------------------------------------
# Volume Hub UAMI — used by kube-system:tesslate-volume-hub
# -----------------------------------------------------------------------------
resource "azurerm_user_assigned_identity" "volume_hub" {
  name                = "${local.cluster_name}-volume-hub-uami"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location

  tags = local.common_tags
}

resource "azurerm_federated_identity_credential" "volume_hub" {
  name                = "${local.cluster_name}-volume-hub-fed"
  resource_group_name = azurerm_resource_group.this.name
  parent_id           = azurerm_user_assigned_identity.volume_hub.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.this.oidc_issuer_url
  subject             = "system:serviceaccount:kube-system:tesslate-volume-hub"
}

resource "azurerm_role_assignment" "volume_hub_blob" {
  scope                = azurerm_storage_container.btrfs_snapshots.resource_manager_id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.volume_hub.principal_id
}

# -----------------------------------------------------------------------------
# cert-manager UAMI — DNS01 challenges via Cloudflare don't strictly need an
# Azure identity, but cert-manager wants a stable SA-bound identity for the
# Key Vault CSI path the cluster may grow into. Created lazily.
# -----------------------------------------------------------------------------
resource "azurerm_user_assigned_identity" "cert_manager" {
  count = var.enable_cert_manager ? 1 : 0

  name                = "${local.cluster_name}-cert-manager-uami"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location

  tags = local.common_tags
}

resource "azurerm_federated_identity_credential" "cert_manager" {
  count = var.enable_cert_manager ? 1 : 0

  name                = "${local.cluster_name}-cert-manager-fed"
  resource_group_name = azurerm_resource_group.this.name
  parent_id           = azurerm_user_assigned_identity.cert_manager[0].id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.this.oidc_issuer_url
  subject             = "system:serviceaccount:cert-manager:cert-manager"
}
