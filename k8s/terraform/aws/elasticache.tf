# =============================================================================
# ElastiCache Redis for Tesslate Studio
# =============================================================================
# Provides Redis as a distributed backplane for horizontal scaling:
# - Pub/Sub for WebSocket fanout across API pods
# - ARQ task queue for agent worker fleet
# - Distributed locking for background loops
# - Session routing for PTY affinity
#
# Cost: ~$13/month (cache.t4g.micro, single node)
# =============================================================================

# -----------------------------------------------------------------------------
# Security Group
# -----------------------------------------------------------------------------
resource "aws_security_group" "redis" {
  count = var.create_elasticache ? 1 : 0

  name_prefix = "${var.project_name}-${var.environment}-redis-"
  vpc_id      = module.vpc.vpc_id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
    description     = "Redis from EKS nodes"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "${var.project_name}-${var.environment}-redis-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# -----------------------------------------------------------------------------
# Subnet Group
# -----------------------------------------------------------------------------
resource "aws_elasticache_subnet_group" "redis" {
  count = var.create_elasticache ? 1 : 0

  name       = "${var.project_name}-${var.environment}-redis-subnet"
  subnet_ids = module.vpc.private_subnets

  tags = merge(local.common_tags, {
    Name = "${var.project_name}-${var.environment}-redis-subnet"
  })
}

# -----------------------------------------------------------------------------
# ElastiCache Replication Group (Redis 7)
# -----------------------------------------------------------------------------
resource "aws_elasticache_replication_group" "redis" {
  count = var.create_elasticache ? 1 : 0

  replication_group_id = "${var.project_name}-${var.environment}-redis"
  description          = "Tesslate ${var.environment} Redis backplane"

  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.elasticache_node_type
  num_cache_clusters   = 1  # Single node for cost savings

  port                 = 6379
  parameter_group_name = "default.redis7"

  subnet_group_name    = aws_elasticache_subnet_group.redis[0].name
  security_group_ids   = [aws_security_group.redis[0].id]

  at_rest_encryption_enabled = true
  transit_encryption_enabled = false  # TLS adds latency; VPC-internal is sufficient

  automatic_failover_enabled = false  # Single node, no failover needed
  multi_az_enabled           = false

  # Maintenance
  maintenance_window       = "Mon:05:00-Mon:06:00"
  snapshot_retention_limit = var.environment == "production" ? 1 : 0
  snapshot_window          = "04:00-05:00"

  apply_immediately = true

  tags = merge(local.common_tags, {
    Name = "${var.project_name}-${var.environment}-redis"
  })
}

# -----------------------------------------------------------------------------
# Scale down K8s-managed Redis when using ElastiCache
# When create_elasticache=true, K8s Redis deployment is scaled to 0
# =============================================================================
resource "kubectl_manifest" "redis_scale_down" {
  count = var.create_elasticache ? 1 : 0

  server_side_apply = true
  force_conflicts   = true

  yaml_body = yamlencode({
    apiVersion = "apps/v1"
    kind       = "Deployment"
    metadata = {
      name      = "redis"
      namespace = "tesslate"
    }
    spec = {
      replicas = 0
    }
  })

  depends_on = [kubernetes_namespace.tesslate]
}
