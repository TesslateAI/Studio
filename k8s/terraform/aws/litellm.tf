# =============================================================================
# LiteLLM Self-Hosted Deployment
# =============================================================================
# Deploys LiteLLM as a self-hosted service in the Tesslate K8s cluster.
# Database can be either RDS (production) or K8s-managed PostgreSQL (beta/dev).
#
# - Both environments get a self-hosted LiteLLM instance
# - Beta: K8s postgres + public access via litellm.{domain}
# - Production: RDS postgres + internal only (ClusterIP, no ingress)
# - Backend LITELLM_API_BASE points to internal K8s service
# =============================================================================

# -----------------------------------------------------------------------------
# RDS PostgreSQL for LiteLLM (when litellm_create_rds = true)
# -----------------------------------------------------------------------------
resource "aws_db_subnet_group" "litellm" {
  count = var.litellm_create_rds ? 1 : 0

  name       = "${var.project_name}-${var.environment}-litellm-db-subnet"
  subnet_ids = module.vpc.private_subnets

  tags = merge(local.common_tags, {
    Name = "${var.project_name}-${var.environment}-litellm-db-subnet"
  })
}

resource "aws_security_group" "litellm_rds" {
  count = var.litellm_create_rds ? 1 : 0

  name_prefix = "${var.project_name}-${var.environment}-litellm-rds-"
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
    Name = "${var.project_name}-${var.environment}-litellm-rds-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_instance" "litellm" {
  count = var.litellm_create_rds ? 1 : 0

  identifier = "${var.project_name}-${var.environment}-litellm-postgres"

  engine         = "postgres"
  engine_version = "15"
  instance_class = var.litellm_rds_instance_class

  allocated_storage     = var.litellm_rds_allocated_storage
  max_allocated_storage = var.litellm_rds_allocated_storage * 2
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "litellm"
  username = "litellm_admin"
  password = var.litellm_db_password

  db_subnet_group_name   = aws_db_subnet_group.litellm[0].name
  vpc_security_group_ids = [aws_security_group.litellm_rds[0].id]

  multi_az               = var.environment == "production"
  publicly_accessible    = false
  deletion_protection    = var.environment == "production"
  skip_final_snapshot    = var.environment != "production"
  final_snapshot_identifier = var.environment == "production" ? "${var.project_name}-${var.environment}-litellm-final-snapshot" : null

  backup_retention_period = var.environment == "production" ? 7 : 1
  backup_window           = "03:00-04:00"
  maintenance_window      = "Mon:04:00-Mon:05:00"

  performance_insights_enabled = var.environment == "production"

  tags = merge(local.common_tags, {
    Name = "${var.project_name}-${var.environment}-litellm-postgres"
  })
}

# -----------------------------------------------------------------------------
# K8s-managed PostgreSQL for LiteLLM (when litellm_create_rds = false)
# -----------------------------------------------------------------------------
resource "kubernetes_persistent_volume_claim" "litellm_postgres" {
  count = var.litellm_create_rds ? 0 : 1

  metadata {
    name      = "litellm-postgres-pvc"
    namespace = kubernetes_namespace.tesslate.metadata[0].name
  }

  wait_until_bound = false

  spec {
    access_modes       = ["ReadWriteOnce"]
    storage_class_name = kubernetes_storage_class.gp3.metadata[0].name
    resources {
      requests = {
        storage = "5Gi"
      }
    }
  }
}

resource "kubernetes_deployment" "litellm_postgres" {
  count = var.litellm_create_rds ? 0 : 1

  metadata {
    name      = "litellm-postgres"
    namespace = kubernetes_namespace.tesslate.metadata[0].name

    labels = {
      app                            = "litellm-postgres"
      "app.kubernetes.io/name"       = "litellm-postgres"
      "app.kubernetes.io/component"  = "database"
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }

  spec {
    replicas = 1

    strategy {
      type = "Recreate"
    }

    selector {
      match_labels = {
        app = "litellm-postgres"
      }
    }

    template {
      metadata {
        labels = {
          app                            = "litellm-postgres"
          "app.kubernetes.io/name"       = "litellm-postgres"
          "app.kubernetes.io/component"  = "database"
          "app.kubernetes.io/managed-by" = "terraform"
        }
      }

      spec {
        container {
          name  = "postgres"
          image = "postgres:15"

          port {
            container_port = 5432
            protocol       = "TCP"
          }

          env {
            name  = "POSTGRES_DB"
            value = "litellm"
          }

          env {
            name  = "POSTGRES_USER"
            value = "litellm_admin"
          }

          env {
            name = "POSTGRES_PASSWORD"
            value_from {
              secret_key_ref {
                name = kubernetes_secret.litellm.metadata[0].name
                key  = "LITELLM_DB_PASSWORD"
              }
            }
          }

          env {
            name  = "PGDATA"
            value = "/var/lib/postgresql/data/pgdata"
          }

          resources {
            requests = {
              memory = "128Mi"
              cpu    = "100m"
            }
            limits = {
              memory = "256Mi"
              cpu    = "250m"
            }
          }

          volume_mount {
            name       = "postgres-data"
            mount_path = "/var/lib/postgresql/data"
          }

          liveness_probe {
            exec {
              command = ["pg_isready", "-U", "litellm_admin", "-d", "litellm"]
            }
            initial_delay_seconds = 15
            period_seconds        = 10
            timeout_seconds       = 5
            failure_threshold     = 3
          }

          readiness_probe {
            exec {
              command = ["pg_isready", "-U", "litellm_admin", "-d", "litellm"]
            }
            initial_delay_seconds = 5
            period_seconds        = 5
            timeout_seconds       = 3
            failure_threshold     = 3
          }
        }

        volume {
          name = "postgres-data"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim.litellm_postgres[0].metadata[0].name
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "litellm_postgres" {
  count = var.litellm_create_rds ? 0 : 1

  metadata {
    name      = "litellm-postgres"
    namespace = kubernetes_namespace.tesslate.metadata[0].name

    labels = {
      app                            = "litellm-postgres"
      "app.kubernetes.io/name"       = "litellm-postgres"
      "app.kubernetes.io/component"  = "database"
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }

  spec {
    type = "ClusterIP"

    selector = {
      app = "litellm-postgres"
    }

    port {
      port        = 5432
      target_port = 5432
      protocol    = "TCP"
    }
  }
}

# -----------------------------------------------------------------------------
# Kubernetes Secret for LiteLLM
# -----------------------------------------------------------------------------
resource "kubernetes_secret" "litellm" {
  metadata {
    name      = "litellm-secrets"
    namespace = kubernetes_namespace.tesslate.metadata[0].name
  }

  data = {
    DATABASE_URL = var.litellm_create_rds ? (
      "postgresql://litellm_admin:${var.litellm_db_password}@${aws_db_instance.litellm[0].endpoint}/litellm"
    ) : (
      "postgresql://litellm_admin:${var.litellm_db_password}@litellm-postgres.${kubernetes_namespace.tesslate.metadata[0].name}.svc.cluster.local:5432/litellm"
    )
    LITELLM_MASTER_KEY        = var.litellm_master_key
    LITELLM_DB_PASSWORD       = var.litellm_db_password
    BEDROCK_API_KEY           = var.bedrock_api_key
    BEDROCK_AWS_REGION        = var.bedrock_aws_region
    VERTEX_PROJECT            = var.vertex_project
    VERTEX_LOCATION           = var.vertex_location
    VERTEX_CREDENTIALS        = var.vertex_credentials != "" ? base64decode(var.vertex_credentials) : ""
    NANOGPT_API_KEY           = var.nanogpt_api_key
    AZURE_API_KEY             = var.azure_api_key
    AZURE_API_BASE            = var.azure_api_base
    AZURE_API_VERSION         = var.azure_api_version
  }

  type = "Opaque"
}

# -----------------------------------------------------------------------------
# Kubernetes ConfigMap for LiteLLM config.yaml
# -----------------------------------------------------------------------------
resource "kubernetes_config_map" "litellm_config" {
  metadata {
    name      = "litellm-config"
    namespace = kubernetes_namespace.tesslate.metadata[0].name
  }

  data = {
    "config.yaml" = file("${path.module}/../../litellm/config.yaml")
  }
}

# -----------------------------------------------------------------------------
# Kubernetes Deployment for LiteLLM
# -----------------------------------------------------------------------------
resource "kubernetes_deployment" "litellm" {
  metadata {
    name      = "litellm"
    namespace = kubernetes_namespace.tesslate.metadata[0].name

    labels = {
      app                            = "litellm"
      "app.kubernetes.io/name"       = "litellm"
      "app.kubernetes.io/component"  = "ai-proxy"
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }

  spec {
    replicas = 1

    selector {
      match_labels = {
        app = "litellm"
      }
    }

    template {
      metadata {
        labels = {
          app                            = "litellm"
          "app.kubernetes.io/name"       = "litellm"
          "app.kubernetes.io/component"  = "ai-proxy"
          "app.kubernetes.io/managed-by" = "terraform"
        }
      }

      spec {
        container {
          name  = "litellm"
          image = "ghcr.io/berriai/litellm:${var.litellm_image_tag}"

          args = ["--port", "4000", "--config", "/app/config.yaml"]

          port {
            container_port = 4000
            protocol       = "TCP"
          }

          env_from {
            secret_ref {
              name = kubernetes_secret.litellm.metadata[0].name
            }
          }

          resources {
            requests = {
              memory = "512Mi"
              cpu    = "250m"
            }
            limits = {
              memory = "2Gi"
              cpu    = "1000m"
            }
          }

          startup_probe {
            http_get {
              path = "/health/liveliness"
              port = 4000
            }
            initial_delay_seconds = 10
            period_seconds        = 10
            timeout_seconds       = 5
            failure_threshold     = 60
          }

          liveness_probe {
            http_get {
              path = "/health/liveliness"
              port = 4000
            }
            period_seconds        = 15
            timeout_seconds       = 5
            failure_threshold     = 3
          }

          readiness_probe {
            http_get {
              path = "/health/readiness"
              port = 4000
            }
            period_seconds        = 10
            timeout_seconds       = 5
            failure_threshold     = 3
          }

          volume_mount {
            name       = "litellm-config"
            mount_path = "/app/config.yaml"
            sub_path   = "config.yaml"
            read_only  = true
          }
        }

        volume {
          name = "litellm-config"
          config_map {
            name = kubernetes_config_map.litellm_config.metadata[0].name
          }
        }
      }
    }
  }

  depends_on = [
    kubernetes_namespace.tesslate,
    kubernetes_secret.litellm
  ]
}

# -----------------------------------------------------------------------------
# Kubernetes Service for LiteLLM (ClusterIP — internal only)
# -----------------------------------------------------------------------------
resource "kubernetes_service" "litellm" {
  metadata {
    name      = "litellm-service"
    namespace = kubernetes_namespace.tesslate.metadata[0].name

    labels = {
      app                            = "litellm"
      "app.kubernetes.io/name"       = "litellm"
      "app.kubernetes.io/component"  = "ai-proxy"
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }

  spec {
    type = "ClusterIP"

    selector = {
      app = "litellm"
    }

    port {
      port        = 4000
      target_port = 4000
      protocol    = "TCP"
    }
  }
}

# -----------------------------------------------------------------------------
# Kubernetes Ingress for LiteLLM (public access — gated by variable)
# -----------------------------------------------------------------------------
resource "kubectl_manifest" "litellm_ingress" {
  count = var.litellm_public_access ? 1 : 0

  yaml_body = yamlencode({
    apiVersion = "networking.k8s.io/v1"
    kind       = "Ingress"
    metadata = {
      name      = "litellm-ingress"
      namespace = kubernetes_namespace.tesslate.metadata[0].name
      annotations = {
        "kubernetes.io/ingress.class"                       = "nginx"
        "cert-manager.io/cluster-issuer"                    = "letsencrypt-prod"
        "nginx.ingress.kubernetes.io/ssl-redirect"          = "true"
        "nginx.ingress.kubernetes.io/force-ssl-redirect"    = "true"
        "nginx.ingress.kubernetes.io/proxy-http-version"    = "1.1"
        "nginx.ingress.kubernetes.io/proxy-read-timeout"    = "3600"
        "nginx.ingress.kubernetes.io/proxy-send-timeout"    = "3600"
        "nginx.ingress.kubernetes.io/proxy-connect-timeout" = "3600"
        "nginx.ingress.kubernetes.io/proxy-body-size"       = "100m"
      }
    }
    spec = {
      ingressClassName = "nginx"
      tls = [{
        hosts = [
          "litellm.${var.domain_name}"
        ]
        secretName = "tesslate-wildcard-tls"
      }]
      rules = [{
        host = "litellm.${var.domain_name}"
        http = {
          paths = [
            {
              path     = "/"
              pathType = "Prefix"
              backend = {
                service = {
                  name = "litellm-service"
                  port = { number = 4000 }
                }
              }
            }
          ]
        }
      }]
    }
  })

  depends_on = [
    kubernetes_namespace.tesslate,
    kubectl_manifest.wildcard_certificate
  ]
}
