# =============================================================================
# Azure Cache for Redis
# =============================================================================
# Equivalent to aws/elasticache.tf. Gated on var.create_redis. Standard SKU
# is reachable via the public endpoint over TLS; Premium requires the redis
# subnet (vnet.tf). All access is via auth-key — VNet rules tighten this for
# Premium.
# =============================================================================

resource "azurerm_redis_cache" "this" {
  count = var.create_redis ? 1 : 0

  name                = "${var.project_name}-${var.environment}-redis"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  capacity            = var.redis_capacity
  family              = var.redis_sku == "Premium" ? "P" : "C"
  sku_name            = var.redis_sku
  non_ssl_port_enabled = false
  minimum_tls_version  = "1.2"

  # Premium SKU supports VNet injection — pin Redis into the redis subnet so
  # AKS pods reach it over a private IP.
  subnet_id = var.redis_sku == "Premium" ? azurerm_subnet.redis[0].id : null

  redis_configuration {
    maxmemory_policy = "allkeys-lru"
  }

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# Scale down K8s-managed Redis when using Azure Cache for Redis. Mirrors
# aws/elasticache.tf:null_resource.redis_scale_down.
# -----------------------------------------------------------------------------
resource "null_resource" "redis_scale_down" {
  count = var.create_redis ? 1 : 0

  provisioner "local-exec" {
    command = "kubectl scale deployment/redis -n tesslate --replicas=0 --timeout=60s 2>/dev/null || true"
  }

  depends_on = [azurerm_kubernetes_cluster.this]
}
