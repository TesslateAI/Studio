# =============================================================================
# Headscale Deployment (VPN Control Server)
# =============================================================================
# Deploys Headscale as native K8s resources — no third-party Helm chart.
# Single-replica with SQLite (WAL mode) for simplicity.
#
# Litestream sidecar continuously replicates SQLite WAL to S3, with an init
# container that restores from S3 on first boot (safe no-op if no replica or
# DB already exists).
#
# Docs: https://headscale.net/
#
# After deploy, create a user and preauthkey:
#   kubectl exec -n headscale deployment/headscale -- headscale users create dev-team
#   kubectl exec -n headscale deployment/headscale -- headscale preauthkeys create \
#     --user dev-team --reusable --expiration 720h
#
# Then connect a client:
#   tailscale up --login-server https://headscale.tesslate.com --authkey <KEY>
# =============================================================================

locals {
  headscale_image  = "headscale/headscale:${var.headscale_image_tag}"
  litestream_image = "litestream/litestream:0.3.13"
  headscale_labels = {
    "app.kubernetes.io/name"     = "headscale"
    "app.kubernetes.io/instance" = "headscale"
  }
}

# -----------------------------------------------------------------------------
# Namespace
# -----------------------------------------------------------------------------
resource "kubernetes_namespace" "headscale" {
  metadata {
    name = "headscale"
  }

  depends_on = [module.eks]
}

# -----------------------------------------------------------------------------
# Litestream Configuration (mounted into sidecar + init container)
# -----------------------------------------------------------------------------
resource "kubernetes_config_map" "litestream" {
  metadata {
    name      = "headscale-litestream"
    namespace = kubernetes_namespace.headscale.metadata[0].name
  }

  data = {
    "litestream.yml" = yamlencode({
      dbs = [{
        path = "/var/lib/headscale/db.sqlite"
        replicas = [{
          type                     = "s3"
          bucket                   = aws_s3_bucket.litestream.id
          path                     = "headscale"
          region                   = var.aws_region
          retention                = "72h"
          retention-check-interval = "1h"
          snapshot-interval        = "24h"
        }]
      }]
    })
  }
}

# -----------------------------------------------------------------------------
# Headscale Configuration (minimal — most config via env vars)
# -----------------------------------------------------------------------------
resource "kubernetes_config_map" "headscale" {
  metadata {
    name      = "headscale-config"
    namespace = kubernetes_namespace.headscale.metadata[0].name
  }

  data = {
    "config.yaml" = yamlencode({
      noise = {
        private_key_path = "/var/lib/headscale/noise_private.key"
      }
    })
  }
}

# -----------------------------------------------------------------------------
# ServiceAccount (IRSA — pod assumes IAM role for S3 access)
# -----------------------------------------------------------------------------
resource "kubernetes_service_account" "headscale" {
  metadata {
    name      = "headscale"
    namespace = kubernetes_namespace.headscale.metadata[0].name
    annotations = {
      "eks.amazonaws.com/role-arn" = module.headscale_irsa.iam_role_arn
    }
    labels = local.headscale_labels
  }
}

# -----------------------------------------------------------------------------
# PersistentVolumeClaim (SQLite database)
# -----------------------------------------------------------------------------
resource "kubernetes_persistent_volume_claim" "headscale" {
  metadata {
    name      = "headscale-data"
    namespace = kubernetes_namespace.headscale.metadata[0].name
    labels    = local.headscale_labels
  }

  wait_until_bound = false

  spec {
    access_modes       = ["ReadWriteOnce"]
    storage_class_name = "gp3"

    resources {
      requests = {
        storage = "5Gi"
      }
    }
  }
}

# -----------------------------------------------------------------------------
# Deployment (headscale + litestream init + litestream sidecar)
# -----------------------------------------------------------------------------
resource "kubernetes_deployment" "headscale" {
  metadata {
    name      = "headscale"
    namespace = kubernetes_namespace.headscale.metadata[0].name
    labels    = local.headscale_labels
  }

  spec {
    replicas = 1

    strategy {
      type = "Recreate"
    }

    selector {
      match_labels = local.headscale_labels
    }

    template {
      metadata {
        labels = local.headscale_labels
      }

      spec {
        service_account_name = kubernetes_service_account.headscale.metadata[0].name

        # --- Init container: restore DB from S3 on first boot ---
        init_container {
          name  = "litestream-restore"
          image = local.litestream_image
          args  = ["restore", "-if-db-not-exists", "-if-replica-exists", "/var/lib/headscale/db.sqlite"]

          volume_mount {
            name       = "data"
            mount_path = "/var/lib/headscale"
          }

          volume_mount {
            name       = "litestream-config"
            mount_path = "/etc/litestream.yml"
            sub_path   = "litestream.yml"
            read_only  = true
          }
        }

        # --- Main container: headscale ---
        container {
          name  = "headscale"
          image = local.headscale_image

          args = ["serve"]

          port {
            name           = "http"
            container_port = 8080
            protocol       = "TCP"
          }

          port {
            name           = "metrics"
            container_port = 9090
            protocol       = "TCP"
          }

          env {
            name  = "HEADSCALE_SERVER_URL"
            value = "https://${var.headscale_subdomain}.${var.domain_name}"
          }
          env {
            name  = "HEADSCALE_LISTEN_ADDR"
            value = "0.0.0.0:8080"
          }
          env {
            name  = "HEADSCALE_METRICS_LISTEN_ADDR"
            value = "0.0.0.0:9090"
          }

          # Database (SQLite — recommended by upstream for single-replica)
          env {
            name  = "HEADSCALE_DATABASE_TYPE"
            value = "sqlite"
          }
          env {
            name  = "HEADSCALE_DATABASE_SQLITE_PATH"
            value = "/var/lib/headscale/db.sqlite"
          }
          env {
            name  = "HEADSCALE_DATABASE_SQLITE_WRITE_AHEAD_LOG"
            value = "true"
          }

          # DNS
          env {
            name  = "HEADSCALE_DNS_MAGIC_DNS"
            value = "true"
          }
          env {
            name  = "HEADSCALE_DNS_BASE_DOMAIN"
            value = var.headscale_base_domain
          }
          env {
            name  = "HEADSCALE_DNS_NAMESERVERS_GLOBAL"
            value = "1.1.1.1 1.0.0.1"
          }

          # IP allocation
          env {
            name  = "HEADSCALE_PREFIXES_V4"
            value = "100.64.0.0/10"
          }
          env {
            name  = "HEADSCALE_PREFIXES_ALLOCATION"
            value = "sequential"
          }

          # DERP — use Tailscale's public relay network (global coverage, no cost)
          env {
            name  = "HEADSCALE_DERP_SERVER_ENABLED"
            value = "false"
          }
          env {
            name  = "HEADSCALE_DERP_URLS"
            value = "https://controlplane.tailscale.com/derpmap/default"
          }

          volume_mount {
            name       = "data"
            mount_path = "/var/lib/headscale"
          }

          volume_mount {
            name       = "headscale-config"
            mount_path = "/etc/headscale/config.yaml"
            sub_path   = "config.yaml"
            read_only  = true
          }

          resources {
            requests = {
              cpu    = "50m"
              memory = "64Mi"
            }
            limits = {
              cpu    = "200m"
              memory = "256Mi"
            }
          }

          liveness_probe {
            http_get {
              path = "/health"
              port = 8080
            }
            initial_delay_seconds = 15
            period_seconds        = 30
          }

          readiness_probe {
            http_get {
              path = "/health"
              port = 8080
            }
            initial_delay_seconds = 5
            period_seconds        = 10
          }
        }

        # --- Sidecar: litestream continuous WAL replication to S3 ---
        container {
          name  = "litestream"
          image = local.litestream_image
          args  = ["replicate"]

          volume_mount {
            name       = "data"
            mount_path = "/var/lib/headscale"
          }

          volume_mount {
            name       = "litestream-config"
            mount_path = "/etc/litestream.yml"
            sub_path   = "litestream.yml"
            read_only  = true
          }

          resources {
            requests = {
              cpu    = "10m"
              memory = "32Mi"
            }
            limits = {
              cpu    = "100m"
              memory = "128Mi"
            }
          }
        }

        # --- Volumes ---
        volume {
          name = "data"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim.headscale.metadata[0].name
          }
        }

        volume {
          name = "litestream-config"
          config_map {
            name = kubernetes_config_map.litestream.metadata[0].name
          }
        }

        volume {
          name = "headscale-config"
          config_map {
            name = kubernetes_config_map.headscale.metadata[0].name
          }
        }
      }
    }
  }

  depends_on = [
    module.eks,
    kubernetes_config_map.litestream,
    kubernetes_config_map.headscale,
  ]
}

# -----------------------------------------------------------------------------
# Service
# -----------------------------------------------------------------------------
resource "kubernetes_service" "headscale" {
  metadata {
    name      = "headscale"
    namespace = kubernetes_namespace.headscale.metadata[0].name
    labels    = local.headscale_labels
  }

  spec {
    selector = local.headscale_labels

    port {
      name        = "http"
      port        = 8080
      target_port = 8080
      protocol    = "TCP"
    }

    port {
      name        = "metrics"
      port        = 9090
      target_port = 9090
      protocol    = "TCP"
    }

    type = "ClusterIP"
  }
}

# -----------------------------------------------------------------------------
# Ingress (NGINX + cert-manager TLS)
# -----------------------------------------------------------------------------
resource "kubernetes_ingress_v1" "headscale" {
  metadata {
    name      = "headscale"
    namespace = kubernetes_namespace.headscale.metadata[0].name
    labels    = local.headscale_labels

    annotations = {
      "cert-manager.io/cluster-issuer" = "letsencrypt-prod"
    }
  }

  spec {
    ingress_class_name = "nginx"

    tls {
      secret_name = "headscale-tls"
      hosts       = ["${var.headscale_subdomain}.${var.domain_name}"]
    }

    rule {
      host = "${var.headscale_subdomain}.${var.domain_name}"

      http {
        path {
          path      = "/"
          path_type = "Prefix"

          backend {
            service {
              name = kubernetes_service.headscale.metadata[0].name
              port {
                number = 8080
              }
            }
          }
        }
      }
    }
  }

  depends_on = [
    helm_release.nginx_ingress,
    kubectl_manifest.letsencrypt_issuer,
  ]
}
