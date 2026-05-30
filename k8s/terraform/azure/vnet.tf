# =============================================================================
# VNet Configuration for OpenSail AKS
# =============================================================================
# Single VNet with three subnets:
#   - aks-nodes       (general AKS node pool subnet)
#   - postgres        (delegated to Microsoft.DBforPostgreSQL/flexibleServers)
#   - redis           (Azure Cache for Redis subnet — premium tier requirement)
#
# AKS uses the Azure CNI Overlay plugin so pods receive overlay IPs and don't
# consume the node subnet CIDR — saves an entire /16 for environments that
# would otherwise burn it on pod IPs.
# =============================================================================

resource "azurerm_virtual_network" "this" {
  name                = "${var.project_name}-${var.environment}-vnet"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  address_space       = [var.vnet_cidr]

  tags = local.common_tags
}

resource "azurerm_subnet" "aks_nodes" {
  name                 = "aks-nodes"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [var.aks_subnet_cidr]

  # Service endpoints reduce egress cost + latency to the Storage Account
  # and Container Registry (parity with AWS VPC S3/ECR endpoints).
  service_endpoints = [
    "Microsoft.Storage",
    "Microsoft.ContainerRegistry",
  ]
}

# -----------------------------------------------------------------------------
# Postgres subnet — delegated to flexibleServers so VNet-injected Postgres
# can sit on a private IP without a public endpoint.
# -----------------------------------------------------------------------------
resource "azurerm_subnet" "postgres" {
  count = var.create_postgres || var.litellm_create_postgres ? 1 : 0

  name                 = "postgres"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [var.postgres_subnet_cidr]

  delegation {
    name = "fs"
    service_delegation {
      name = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action",
      ]
    }
  }
}

# -----------------------------------------------------------------------------
# Redis subnet — only required for Premium SKU (VNet injection). Standard
# SKU is reachable via its public endpoint and skips this subnet.
# -----------------------------------------------------------------------------
resource "azurerm_subnet" "redis" {
  count = var.create_redis && var.redis_sku == "Premium" ? 1 : 0

  name                 = "redis"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [var.redis_subnet_cidr]
}

# -----------------------------------------------------------------------------
# Private DNS zone for Postgres Flexible Server VNet integration
# -----------------------------------------------------------------------------
resource "azurerm_private_dns_zone" "postgres" {
  count = var.create_postgres || var.litellm_create_postgres ? 1 : 0

  name                = "${var.project_name}-${var.environment}.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.this.name

  tags = local.common_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  count = var.create_postgres || var.litellm_create_postgres ? 1 : 0

  name                  = "${var.project_name}-${var.environment}-postgres-link"
  resource_group_name   = azurerm_resource_group.this.name
  private_dns_zone_name = azurerm_private_dns_zone.postgres[0].name
  virtual_network_id    = azurerm_virtual_network.this.id

  tags = local.common_tags
}
