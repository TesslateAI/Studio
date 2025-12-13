# =============================================================================
# Kubernetes Resources for Tesslate Studio
# =============================================================================
# Creates Kubernetes namespaces, secrets, and configmaps needed for
# the Tesslate application deployment.
# =============================================================================

# -----------------------------------------------------------------------------
# Tesslate Namespace
# -----------------------------------------------------------------------------
resource "kubernetes_namespace" "tesslate" {
  metadata {
    name = "tesslate"

    labels = {
      "app.kubernetes.io/name"       = "tesslate"
      "app.kubernetes.io/managed-by" = "terraform"
      "environment"                  = var.environment
    }
  }

  depends_on = [module.eks]
}

# -----------------------------------------------------------------------------
# Service Account for Tesslate Backend (with IRSA)
# -----------------------------------------------------------------------------
resource "kubernetes_service_account" "tesslate_backend" {
  metadata {
    name      = "tesslate-backend-sa"
    namespace = kubernetes_namespace.tesslate.metadata[0].name

    annotations = {
      "eks.amazonaws.com/role-arn" = module.tesslate_backend_irsa.iam_role_arn
    }

    labels = {
      "app.kubernetes.io/name"      = "tesslate-backend"
      "app.kubernetes.io/component" = "backend"
    }
  }
}

# -----------------------------------------------------------------------------
# PostgreSQL Secret
# -----------------------------------------------------------------------------
resource "kubernetes_secret" "postgres" {
  metadata {
    name      = "postgres-secret"
    namespace = kubernetes_namespace.tesslate.metadata[0].name
  }

  data = {
    POSTGRES_DB       = var.create_rds ? var.rds_database_name : "tesslate"
    POSTGRES_USER     = var.create_rds ? var.rds_username : "tesslate_user"
    POSTGRES_PASSWORD = var.postgres_password
  }

  type = "Opaque"
}

# -----------------------------------------------------------------------------
# S3 Credentials Secret
# Note: With IRSA, we don't need actual keys, but the app still expects the secret
# -----------------------------------------------------------------------------
resource "kubernetes_secret" "s3_credentials" {
  metadata {
    name      = "s3-credentials"
    namespace = kubernetes_namespace.tesslate.metadata[0].name
  }

  data = {
    S3_ACCESS_KEY_ID     = ""  # Not needed with IRSA
    S3_SECRET_ACCESS_KEY = ""  # Not needed with IRSA
    S3_BUCKET_NAME       = aws_s3_bucket.tesslate_projects.id
    S3_ENDPOINT_URL      = ""  # Empty = use native AWS S3
    S3_REGION            = var.aws_region
  }

  type = "Opaque"
}

# -----------------------------------------------------------------------------
# Application Secrets
# -----------------------------------------------------------------------------
resource "kubernetes_secret" "app_secrets" {
  metadata {
    name      = "tesslate-app-secrets"
    namespace = kubernetes_namespace.tesslate.metadata[0].name
  }

  data = {
    SECRET_KEY = var.app_secret_key
    DATABASE_URL = var.create_rds ? (
      "postgresql+asyncpg://${var.rds_username}:${var.postgres_password}@${aws_db_instance.tesslate[0].endpoint}/${var.rds_database_name}"
    ) : (
      "postgresql+asyncpg://tesslate_user:${var.postgres_password}@postgres:5432/tesslate"
    )

    # LiteLLM
    LITELLM_API_BASE       = var.litellm_api_base
    LITELLM_MASTER_KEY     = var.litellm_master_key
    LITELLM_DEFAULT_MODELS = var.litellm_default_models
    LITELLM_TEAM_ID        = "default"
    LITELLM_EMAIL_DOMAIN   = var.domain_name
    LITELLM_INITIAL_BUDGET = "10.0"

    # CORS & Domain
    CORS_ORIGINS      = "https://${var.domain_name},https://*.${var.domain_name}"
    ALLOWED_HOSTS     = "${var.domain_name},*.${var.domain_name}"
    APP_DOMAIN        = var.domain_name
    APP_BASE_URL      = "https://${var.domain_name}"
    DEV_SERVER_BASE_URL = "https://*.${var.domain_name}"

    # OAuth - Google
    GOOGLE_CLIENT_ID           = var.google_client_id
    GOOGLE_CLIENT_SECRET       = var.google_client_secret
    GOOGLE_OAUTH_REDIRECT_URI  = "https://${var.domain_name}/api/auth/google/callback"

    # OAuth - GitHub
    GITHUB_CLIENT_ID           = var.github_client_id
    GITHUB_CLIENT_SECRET       = var.github_client_secret
    GITHUB_OAUTH_REDIRECT_URI  = "https://${var.domain_name}/api/auth/github/callback"

    # Stripe
    STRIPE_SECRET_KEY    = var.stripe_secret_key
    STRIPE_WEBHOOK_SECRET = var.stripe_webhook_secret
  }

  type = "Opaque"
}

# -----------------------------------------------------------------------------
# Tesslate ConfigMap
# -----------------------------------------------------------------------------
resource "kubernetes_config_map" "tesslate_config" {
  metadata {
    name      = "tesslate-config"
    namespace = kubernetes_namespace.tesslate.metadata[0].name
  }

  data = {
    DEPLOYMENT_MODE              = "kubernetes"
    K8S_NAMESPACE_PER_PROJECT    = "true"
    K8S_ENABLE_NETWORK_POLICIES  = "true"
    devserver_image              = "${aws_ecr_repository.devserver.repository_url}:latest"
    registry_url                 = split("/", aws_ecr_repository.backend.repository_url)[0]
    aws_region                   = var.aws_region
    s3_bucket_name               = aws_s3_bucket.tesslate_projects.id
  }
}

# -----------------------------------------------------------------------------
# Wildcard TLS Certificate
# -----------------------------------------------------------------------------
resource "kubectl_manifest" "wildcard_certificate" {
  count = var.enable_cert_manager ? 1 : 0

  yaml_body = yamlencode({
    apiVersion = "cert-manager.io/v1"
    kind       = "Certificate"
    metadata = {
      name      = "tesslate-wildcard-tls"
      namespace = "tesslate"
    }
    spec = {
      secretName = "tesslate-wildcard-tls"
      issuerRef = {
        name = "letsencrypt-prod"
        kind = "ClusterIssuer"
      }
      commonName = var.domain_name
      dnsNames = [
        var.domain_name,
        "*.${var.domain_name}"
      ]
    }
  })

  depends_on = [
    kubernetes_namespace.tesslate,
    kubectl_manifest.letsencrypt_issuer
  ]
}

# -----------------------------------------------------------------------------
# Network Policy for Project Namespaces (template)
# This is applied dynamically by the backend when creating project namespaces
# -----------------------------------------------------------------------------
resource "kubernetes_network_policy" "tesslate_default" {
  metadata {
    name      = "tesslate-default-policy"
    namespace = kubernetes_namespace.tesslate.metadata[0].name
  }

  spec {
    pod_selector {}
    policy_types = ["Ingress", "Egress"]

    # Allow ingress from ingress-nginx namespace
    ingress {
      from {
        namespace_selector {
          match_labels = {
            "kubernetes.io/metadata.name" = "ingress-nginx"
          }
        }
      }
    }

    # Allow internal communication within namespace
    ingress {
      from {
        pod_selector {}
      }
    }

    # Allow all egress (for external APIs, npm, etc.)
    egress {
      to {
        ip_block {
          cidr = "0.0.0.0/0"
        }
      }
    }
  }
}

# -----------------------------------------------------------------------------
# Optional: RDS PostgreSQL (if not using K8s-managed postgres)
# -----------------------------------------------------------------------------
resource "aws_db_subnet_group" "tesslate" {
  count = var.create_rds ? 1 : 0

  name       = "${var.project_name}-${var.environment}-db-subnet"
  subnet_ids = module.vpc.private_subnets

  tags = merge(local.common_tags, {
    Name = "${var.project_name}-${var.environment}-db-subnet"
  })
}

resource "aws_security_group" "rds" {
  count = var.create_rds ? 1 : 0

  name_prefix = "${var.project_name}-${var.environment}-rds-"
  vpc_id      = module.vpc.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
    description     = "PostgreSQL from EKS nodes"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "${var.project_name}-${var.environment}-rds-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_instance" "tesslate" {
  count = var.create_rds ? 1 : 0

  identifier = "${var.project_name}-${var.environment}-postgres"

  engine         = "postgres"
  engine_version = "15"
  instance_class = var.rds_instance_class

  allocated_storage     = var.rds_allocated_storage
  max_allocated_storage = var.rds_allocated_storage * 2
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = var.rds_database_name
  username = var.rds_username
  password = var.postgres_password

  db_subnet_group_name   = aws_db_subnet_group.tesslate[0].name
  vpc_security_group_ids = [aws_security_group.rds[0].id]

  multi_az               = var.environment == "production"
  publicly_accessible    = false
  deletion_protection    = var.environment == "production"
  skip_final_snapshot    = var.environment != "production"
  final_snapshot_identifier = var.environment == "production" ? "${var.project_name}-${var.environment}-final-snapshot" : null

  backup_retention_period = var.environment == "production" ? 7 : 1
  backup_window           = "03:00-04:00"
  maintenance_window      = "Mon:04:00-Mon:05:00"

  performance_insights_enabled = var.environment == "production"

  tags = merge(local.common_tags, {
    Name = "${var.project_name}-${var.environment}-postgres"
  })
}
