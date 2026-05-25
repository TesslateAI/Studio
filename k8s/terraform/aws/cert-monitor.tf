# =============================================================================
# Certificate expiry monitor
# =============================================================================
# Cluster-scoped daily check that surfaces stuck or expiring cert-manager
# Certificates *before* they break production. Pages two ways:
#   1) stdout / pod logs (always)              — kubectl logs CronJob/...
#   2) Slack webhook (only if configured)      — set var.cert_alert_webhook_url
#
# Triggers an alert when ANY Certificate in any namespace:
#   - has notAfter within --warn-days (default 14)
#   - has Issuing=True for more than --stuck-hours (default 24)
#   - has Ready=False with reason!=Issuing for more than --failed-hours (default 1)
#
# This is a deliberate alternative to a full Prometheus stack so we don't
# introduce a dependency just for cert monitoring. If/when kube-prometheus
# lands, replace this with PrometheusRule on certmanager_* metrics.
# =============================================================================

resource "kubernetes_config_map" "cert_monitor_script" {
  count = var.enable_cert_manager ? 1 : 0

  metadata {
    name      = "cert-monitor-script"
    namespace = "cert-manager"
  }

  data = {
    "check-certs.sh" = file("${path.module}/cert-monitor/check-certs.sh")
  }

  depends_on = [helm_release.cert_manager]
}

resource "kubernetes_service_account" "cert_monitor" {
  count = var.enable_cert_manager ? 1 : 0

  metadata {
    name      = "cert-monitor"
    namespace = "cert-manager"
  }

  depends_on = [helm_release.cert_manager]
}

resource "kubernetes_cluster_role" "cert_monitor" {
  count = var.enable_cert_manager ? 1 : 0

  metadata {
    name = "cert-monitor"
  }

  # Read-only on Certificates, CertificateRequests, Orders, Challenges across
  # every namespace. No mutations — this job only reports.
  rule {
    api_groups = ["cert-manager.io"]
    resources  = ["certificates", "certificaterequests"]
    verbs      = ["get", "list"]
  }
  rule {
    api_groups = ["acme.cert-manager.io"]
    resources  = ["orders", "challenges"]
    verbs      = ["get", "list"]
  }
}

resource "kubernetes_cluster_role_binding" "cert_monitor" {
  count = var.enable_cert_manager ? 1 : 0

  metadata {
    name = "cert-monitor"
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = kubernetes_cluster_role.cert_monitor[0].metadata[0].name
  }

  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account.cert_monitor[0].metadata[0].name
    namespace = "cert-manager"
  }
}

# Optional Slack webhook. Stored as a Secret so it can be rotated without
# re-applying TF; if var is empty we still create an empty secret so the
# CronJob env var resolves cleanly. The script treats empty as "log-only".
resource "kubernetes_secret" "cert_monitor_webhook" {
  count = var.enable_cert_manager ? 1 : 0

  metadata {
    name      = "cert-monitor-webhook"
    namespace = "cert-manager"
  }

  data = {
    url = var.cert_alert_webhook_url
  }

  depends_on = [helm_release.cert_manager]
}

resource "kubernetes_cron_job_v1" "cert_monitor" {
  count = var.enable_cert_manager ? 1 : 0

  metadata {
    name      = "cert-monitor"
    namespace = "cert-manager"
  }

  spec {
    schedule                      = "0 */6 * * *" # every 6 hours
    concurrency_policy            = "Forbid"
    successful_jobs_history_limit = 1
    failed_jobs_history_limit     = 3
    starting_deadline_seconds     = 600

    job_template {
      metadata {}
      spec {
        backoff_limit            = 1
        ttl_seconds_after_finished = 86400 # 1 day

        template {
          metadata {}
          spec {
            service_account_name = kubernetes_service_account.cert_monitor[0].metadata[0].name
            restart_policy       = "OnFailure"

            container {
              name = "monitor"
              # alpine/k8s bundles kubectl + helm + jq + python3 + bash on
              # a small alpine base, which is what the check-certs.sh
              # script needs. registry.k8s.io/kubectl is distroless and
              # lacks /bin/sh + python3, so it can't run shell scripts.
              # bitnami/kubectl was deprecated in late 2025.
              image = "alpine/k8s:1.30.0"

              env {
                name = "WEBHOOK_URL"
                value_from {
                  secret_key_ref {
                    name = kubernetes_secret.cert_monitor_webhook[0].metadata[0].name
                    key  = "url"
                  }
                }
              }
              env {
                name  = "CLUSTER_LABEL"
                value = "${var.project_name}-${var.environment}"
              }
              env {
                name  = "WARN_DAYS"
                value = "14"
              }
              env {
                name  = "STUCK_HOURS"
                value = "24"
              }

              command = ["/bin/bash", "/scripts/check-certs.sh"]

              volume_mount {
                name       = "script"
                mount_path = "/scripts"
                read_only  = true
              }

              resources {
                requests = {
                  cpu    = "50m"
                  memory = "64Mi"
                }
                limits = {
                  cpu    = "200m"
                  memory = "128Mi"
                }
              }
            }

            volume {
              name = "script"
              config_map {
                name         = kubernetes_config_map.cert_monitor_script[0].metadata[0].name
                default_mode = "0755"
              }
            }
          }
        }
      }
    }
  }

  depends_on = [
    kubernetes_config_map.cert_monitor_script,
    kubernetes_service_account.cert_monitor,
    kubernetes_cluster_role_binding.cert_monitor,
    kubernetes_secret.cert_monitor_webhook,
  ]
}
