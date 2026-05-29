# =============================================================================
# Terraform Outputs for OpenSail Azure AKS
# =============================================================================

# -----------------------------------------------------------------------------
# Cluster
# -----------------------------------------------------------------------------
output "cluster_name" {
  description = "AKS cluster name"
  value       = azurerm_kubernetes_cluster.this.name
}

output "resource_group_name" {
  description = "Resource group holding every Azure resource for this env"
  value       = azurerm_resource_group.this.name
}

output "kube_config_command" {
  description = "Command to configure kubectl for this cluster"
  value       = "az aks get-credentials --name ${azurerm_kubernetes_cluster.this.name} --resource-group ${azurerm_resource_group.this.name} --overwrite-existing"
}

output "cluster_oidc_issuer_url" {
  description = "OIDC issuer URL for Workload Identity federation"
  value       = azurerm_kubernetes_cluster.this.oidc_issuer_url
}

# -----------------------------------------------------------------------------
# Networking
# -----------------------------------------------------------------------------
output "vnet_id" {
  description = "VNet ID"
  value       = azurerm_virtual_network.this.id
}

output "aks_subnet_id" {
  description = "Subnet ID hosting AKS nodes"
  value       = azurerm_subnet.aks_nodes.id
}

# -----------------------------------------------------------------------------
# ACR
# -----------------------------------------------------------------------------
output "acr_login_server" {
  description = "ACR login server (registry hostname)"
  value       = azurerm_container_registry.this.login_server
}

output "acr_backend_repository_url" { value = local.acr_backend_url }
output "acr_frontend_repository_url" { value = local.acr_frontend_url }
output "acr_devserver_repository_url" { value = local.acr_devserver_url }
output "acr_ast_repository_url" { value = local.acr_ast_url }
output "acr_marketplace_repository_url" { value = local.acr_marketplace_url }
output "acr_btrfs_csi_repository_url" { value = local.acr_btrfs_csi_url }

output "image_tag" {
  description = "Image tag used for ACR images"
  value       = local.image_tag
}

# -----------------------------------------------------------------------------
# Storage
# -----------------------------------------------------------------------------
output "storage_account_name" {
  description = "Storage Account name (Blob endpoint host = {name}.blob.core.windows.net)"
  value       = azurerm_storage_account.this.name
}

output "projects_container_name" { value = azurerm_storage_container.projects.name }
output "btrfs_snapshots_container_name" { value = azurerm_storage_container.btrfs_snapshots.name }
output "marketplace_bundles_container_name" { value = azurerm_storage_container.marketplace_bundles.name }

# -----------------------------------------------------------------------------
# Workload Identity UAMIs
# -----------------------------------------------------------------------------
output "backend_uami_client_id" { value = azurerm_user_assigned_identity.backend.client_id }
output "btrfs_csi_uami_client_id" { value = azurerm_user_assigned_identity.btrfs_csi.client_id }
output "volume_hub_uami_client_id" { value = azurerm_user_assigned_identity.volume_hub.client_id }

# -----------------------------------------------------------------------------
# Database
# -----------------------------------------------------------------------------
output "postgres_endpoint" {
  description = "Postgres Flexible Server FQDN (or fallback message)"
  value       = var.create_postgres ? "${azurerm_postgresql_flexible_server.this[0].name}.${azurerm_private_dns_zone.postgres[0].name}" : "Using K8s-managed PostgreSQL"
}

# -----------------------------------------------------------------------------
# Redis
# -----------------------------------------------------------------------------
output "redis_endpoint" {
  description = "Azure Cache for Redis hostname (or fallback message)"
  value       = var.create_redis ? azurerm_redis_cache.this[0].hostname : "Using K8s-managed Redis"
}

# -----------------------------------------------------------------------------
# Key Vault (tfvars backup)
# -----------------------------------------------------------------------------
output "key_vault_name" {
  description = "Key Vault holding the env's tfvars backup + future secret bundles"
  value       = azurerm_key_vault.this.name
}

output "tfvars_secret_name" {
  description = "Name of the Key Vault secret that holds this env's terraform.{env}.tfvars (managed by scripts/terraform/azure-secrets.sh)"
  value       = "<AWS_IAM_USER>-${var.environment}"
}

# -----------------------------------------------------------------------------
# Domain
# -----------------------------------------------------------------------------
output "domain_configuration" {
  description = "Domain configuration for the application"
  value = {
    main_domain     = var.domain_name
    wildcard_domain = "*.${var.domain_name}"
    app_url         = "https://${var.domain_name}"
    project_urls    = "https://<project>-<container>.${var.domain_name}"
  }
}
