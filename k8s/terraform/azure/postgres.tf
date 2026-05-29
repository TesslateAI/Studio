# =============================================================================
# Azure Database for PostgreSQL Flexible Server
# =============================================================================
# Equivalent to aws/kubernetes.tf's RDS resource. Gated on var.create_postgres
# so beta can keep using the in-cluster postgres pod and only production pays
# for a managed flexible server.
#
# Deployed into the delegated `postgres` subnet (vnet.tf) — no public endpoint.
# =============================================================================

# Random suffix keeps the server name unique across re-applies. Postgres
# Flexible Server names must be globally unique.
resource "random_id" "postgres_suffix" {
  count       = var.create_postgres ? 1 : 0
  byte_length = 3
}

resource "azurerm_postgresql_flexible_server" "this" {
  count = var.create_postgres ? 1 : 0

  name                   = "${var.project_name}-${var.environment}-pg-${random_id.postgres_suffix[0].hex}"
  resource_group_name    = azurerm_resource_group.this.name
  location               = azurerm_resource_group.this.location
  version                = var.postgres_version
  delegated_subnet_id    = azurerm_subnet.postgres[0].id
  private_dns_zone_id    = azurerm_private_dns_zone.postgres[0].id
  administrator_login    = var.postgres_admin_username
  administrator_password = var.postgres_password
  zone                   = "1"

  storage_mb = var.postgres_storage_mb
  sku_name   = var.postgres_sku_name

  backup_retention_days        = var.environment == "production" ? 14 : 7
  geo_redundant_backup_enabled = var.environment == "production"

  high_availability {
    mode = var.environment == "production" ? "ZoneRedundant" : "Disabled"
    # standby_availability_zone only set when HA enabled — Azure rejects it
    # when Disabled and there's no clean conditional block expression.
  }

  tags = local.common_tags

  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres]
}

resource "azurerm_postgresql_flexible_server_database" "tesslate" {
  count = var.create_postgres ? 1 : 0

  name      = var.postgres_database_name
  server_id = azurerm_postgresql_flexible_server.this[0].id
  charset   = "UTF8"
  collation = "en_US.utf8"

  lifecycle {
    prevent_destroy = false
  }
}

# Marketplace database — siblings tesslate_marketplace lives next to the
# orchestrator's tesslate db on the same server. Matches the AWS layout.
resource "azurerm_postgresql_flexible_server_database" "marketplace" {
  count = var.create_postgres ? 1 : 0

  name      = "tesslate_marketplace"
  server_id = azurerm_postgresql_flexible_server.this[0].id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# -----------------------------------------------------------------------------
# Scale down K8s postgres if it exists (no-op if deployment doesn't exist).
# Mirrors aws/kubernetes.tf:null_resource.postgres_scale_down.
# -----------------------------------------------------------------------------
resource "null_resource" "postgres_scale_down" {
  count = var.create_postgres ? 1 : 0

  provisioner "local-exec" {
    command = "kubectl scale deployment/postgres -n tesslate --replicas=0 2>/dev/null || true"
  }

  depends_on = [azurerm_kubernetes_cluster.this]
}
