# =============================================================================
# Helm Releases for OpenSail AKS
# =============================================================================
# Installs cluster components — mirrors aws/helm.tf one-for-one. The only
# AKS-specific change is the NGINX ingress LoadBalancer annotation set
# (service.beta.kubernetes.io/azure-load-balancer-*) and the Workload
# Identity SA annotation on cert-manager.
# =============================================================================

# -----------------------------------------------------------------------------
# NGINX Ingress Controller (Azure Standard LB)
# -----------------------------------------------------------------------------
resource "helm_release" "nginx_ingress" {
  name             = "ingress-nginx"
  repository       = "https://kubernetes.github.io/ingress-nginx"
  chart            = "ingress-nginx"
  version          = "4.9.0"
  namespace        = "ingress-nginx"
  create_namespace = true

  # Helm's default 5-min wait expires before Azure programs the Standard LB
  # public IP on a fresh subscription (the LB programming can take 8+ min).
  # We don't need Helm to wait at all because `null_resource.wait_for_lb_ip`
  # in dns.tf polls until the IP appears.
  wait    = false
  timeout = 900

  values = [
    yamlencode({
      controller = {
        replicaCount = var.nginx_ingress_replicas

        service = {
          type = "LoadBalancer"
          # externalTrafficPolicy=Local is REQUIRED on AKS with Cilium kube-
          # proxy replacement + Azure Standard LB (floating IP enabled).
          # With Cluster ETP the LB delivers packets with destination IP
          # = LB VIP and Cilium's BPF datapath drops the reply path (the
          # NodePort flow doesn't DNAT back through the originating node).
          # Symptom: external TCP connects succeed but TLS Client Hello /
          # HTTP requests time out with no response. Local ETP makes the
          # LB target only nodes hosting ingress controller pods and
          # disables Cluster-mode SNAT, which works correctly.
          externalTrafficPolicy = "Local"

          # The public IP lives in the AKS node resource group (MC_*) by
          # default — that's the only RG the cluster's SystemAssigned
          # identity has Network Contributor on. Overriding via
          # `azure-load-balancer-resource-group` would need extra perms.
          annotations = {
            "service.beta.kubernetes.io/azure-load-balancer-internal" = "false"
          }
        }

        config = {
          "use-proxy-protocol"             = "false"
          "use-forwarded-headers"          = "true"
          "compute-full-forwarded-for"     = "true"
          "proxy-body-size"                = "50m"
          "proxy-buffering"                = "off"
          "proxy-read-timeout"             = "3600"
          "proxy-send-timeout"             = "3600"
          "upstream-keepalive-connections" = "10000"
          "upstream-keepalive-timeout"     = "60"
        }

        resources = {
          requests = { cpu = "100m", memory = "128Mi" }
          limits   = { cpu = "500m", memory = "512Mi" }
        }

        metrics = {
          enabled        = true
          serviceMonitor = { enabled = false }
        }

        admissionWebhooks = { enabled = true }
      }
    })
  ]

  depends_on = [time_sleep.wait_for_aks]
}

# -----------------------------------------------------------------------------
# cert-manager — same chart, Workload Identity annotation on the SA
# -----------------------------------------------------------------------------
resource "helm_release" "cert_manager" {
  count = var.enable_cert_manager ? 1 : 0

  name             = "cert-manager"
  repository       = "https://charts.jetstack.io"
  chart            = "cert-manager"
  version          = "v1.20.2"
  namespace        = "cert-manager"
  create_namespace = true

  values = [
    yamlencode({
      crds = {
        enabled = true
        keep    = true
      }

      serviceAccount = {
        annotations = {
          "azure.workload.identity/client-id" = azurerm_user_assigned_identity.cert_manager[0].client_id
          "azure.workload.identity/tenant-id" = data.azurerm_client_config.current.tenant_id
        }
        labels = {
          "azure.workload.identity/use" = "true"
        }
      }

      resources = {
        requests = { cpu = "50m", memory = "64Mi" }
        limits   = { cpu = "200m", memory = "256Mi" }
      }

      dns01RecursiveNameservers     = "1.1.1.1:53,8.8.8.8:53"
      dns01RecursiveNameserversOnly = true

      networkPolicy = { enabled = false }
      cainjector    = { networkPolicy = { enabled = false } }
      webhook       = { networkPolicy = { enabled = false } }
    })
  ]

  depends_on = [time_sleep.wait_for_aks]
}

# -----------------------------------------------------------------------------
# kubernetes-reflector (auto-sync wildcard TLS into project namespaces)
# -----------------------------------------------------------------------------
resource "helm_release" "reflector" {
  count = var.enable_cert_manager ? 1 : 0

  name             = "reflector"
  repository       = "https://emberstack.github.io/helm-charts"
  chart            = "reflector"
  version          = "9.1.18"
  namespace        = "kube-system"
  create_namespace = false

  values = [
    yamlencode({
      resources = {
        requests = { cpu = "10m", memory = "32Mi" }
        limits   = { cpu = "100m", memory = "128Mi" }
      }
    })
  ]

  depends_on = [helm_release.cert_manager]
}

# -----------------------------------------------------------------------------
# Cloudflare API Token Secret for cert-manager and external-dns
# -----------------------------------------------------------------------------
resource "kubernetes_namespace" "external_dns" {
  metadata { name = "external-dns" }

  depends_on = [time_sleep.wait_for_aks]
}

resource "kubernetes_secret" "cloudflare_api_token" {
  metadata {
    name      = "cloudflare-api-token"
    namespace = "cert-manager"
  }

  data = {
    api-token = var.cloudflare_api_token
  }

  depends_on = [helm_release.cert_manager]
}

resource "kubernetes_secret" "cloudflare_api_token_external_dns" {
  metadata {
    name      = "cloudflare-api-token"
    namespace = "external-dns"
  }

  data = {
    api-token = var.cloudflare_api_token
  }

  depends_on = [kubernetes_namespace.external_dns]
}

# -----------------------------------------------------------------------------
# ClusterIssuer for Let's Encrypt with Cloudflare DNS-01 challenge
# -----------------------------------------------------------------------------
resource "kubectl_manifest" "letsencrypt_issuer" {
  count = var.enable_cert_manager ? 1 : 0

  yaml_body = yamlencode({
    apiVersion = "cert-manager.io/v1"
    kind       = "ClusterIssuer"
    metadata   = { name = "letsencrypt-prod" }
    spec = {
      acme = {
        server              = "https://acme-v02.api.letsencrypt.org/directory"
        email               = "admin@${var.domain_name}"
        privateKeySecretRef = { name = "letsencrypt-prod" }
        solvers = [
          {
            dns01 = {
              cloudflare = {
                email = "admin@${var.domain_name}"
                apiTokenSecretRef = {
                  name = "cloudflare-api-token"
                  key  = "api-token"
                }
              }
            }
            selector = {
              dnsZones = [local.cloudflare_zone_name]
            }
          }
        ]
      }
    }
  })

  depends_on = [
    helm_release.cert_manager,
    kubernetes_secret.cloudflare_api_token,
  ]
}

resource "kubernetes_secret" "cloudflare_zone_id" {
  count = var.enable_cert_manager && var.cloudflare_zone_id != "" ? 1 : 0

  metadata {
    name      = "cloudflare-zone-id"
    namespace = "cert-manager"
  }

  data = {
    zone-id = var.cloudflare_zone_id
  }

  depends_on = [helm_release.cert_manager]
}

# Staging issuer for testing
resource "kubectl_manifest" "letsencrypt_staging_issuer" {
  count = var.enable_cert_manager ? 1 : 0

  yaml_body = yamlencode({
    apiVersion = "cert-manager.io/v1"
    kind       = "ClusterIssuer"
    metadata   = { name = "letsencrypt-staging" }
    spec = {
      acme = {
        server              = "https://acme-staging-v02.api.letsencrypt.org/directory"
        email               = "admin@${var.domain_name}"
        privateKeySecretRef = { name = "letsencrypt-staging" }
        solvers = [
          {
            dns01 = {
              cloudflare = {
                email = "admin@${var.domain_name}"
                apiTokenSecretRef = {
                  name = "cloudflare-api-token"
                  key  = "api-token"
                }
              }
            }
            selector = {
              dnsZones = [local.cloudflare_zone_name]
            }
          }
        ]
      }
    }
  })

  depends_on = [
    helm_release.cert_manager,
    kubernetes_secret.cloudflare_api_token,
  ]
}

# -----------------------------------------------------------------------------
# external-dns (Cloudflare provider)
# -----------------------------------------------------------------------------
resource "helm_release" "external_dns" {
  count = var.enable_external_dns ? 1 : 0

  name             = "external-dns"
  repository       = "https://kubernetes-sigs.github.io/external-dns"
  chart            = "external-dns"
  version          = "1.14.0"
  namespace        = "external-dns"
  create_namespace = false

  # Same rationale as nginx_ingress: on a fresh cluster the chart can take
  # longer than Helm's 5-min default to settle because nodes are still
  # finalising autoscale + cilium policy programming in parallel. Helm
  # treats this as failed even when the pod is actually Running.
  wait    = false
  timeout = 900

  values = [
    yamlencode({
      provider = "cloudflare"

      cloudflare = {
        apiToken = ""
        proxied  = true
      }

      env = [
        {
          name = "CF_API_TOKEN"
          valueFrom = {
            secretKeyRef = {
              name = "cloudflare-api-token"
              key  = "api-token"
            }
          }
        }
      ]

      domainFilters = [local.cloudflare_zone_name]
      zoneIDFilters = var.cloudflare_zone_id != "" ? [var.cloudflare_zone_id] : []

      policy  = "sync"
      sources = ["ingress", "service"]

      # Same hard namespace filter as the AWS overlay — don't fan out per-project
      # CNAMEs; the wildcard covers them and protects the zone record cap.
      extraArgs  = ["--namespace=tesslate"]
      txtOwnerId = "${var.project_name}-${var.environment}"

      resources = {
        requests = { cpu = "50m", memory = "64Mi" }
        limits   = { cpu = "200m", memory = "256Mi" }
      }

      interval = "1m"
      logLevel = "info"
    })
  ]

  depends_on = [
    time_sleep.wait_for_aks,
    kubernetes_secret.cloudflare_api_token_external_dns,
  ]
}

# -----------------------------------------------------------------------------
# Metrics Server — NOT installed via Helm on AKS.
# AKS ships metrics-server as a managed addon (enabled by default), and our
# Helm release would race the addon for ownership of the `metrics-server`
# ServiceAccount in kube-system. The `enable_metrics_server` var is kept on
# the AWS stack and ignored here.
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# CSI Snapshot Controller — required for Azure Disk VolumeSnapshots and
# the btrfs CSI driver's VolumeSnapshot CRs. AKS ships this as a managed
# addon on recent versions; older clusters need the Helm release.
# -----------------------------------------------------------------------------
resource "helm_release" "snapshot_controller" {
  name       = "snapshot-controller"
  repository = "https://piraeus.io/helm-charts"
  chart      = "snapshot-controller"
  version    = "3.0.6"
  namespace  = "kube-system"

  values = [
    yamlencode({
      controller = {
        resources = {
          requests = { cpu = "10m", memory = "32Mi" }
          limits   = { cpu = "100m", memory = "128Mi" }
        }
      }
      webhook = {
        enabled = true
        resources = {
          requests = { cpu = "10m", memory = "32Mi" }
          limits   = { cpu = "100m", memory = "128Mi" }
        }
      }
    })
  ]

  depends_on = [time_sleep.wait_for_aks]
}

# -----------------------------------------------------------------------------
# Workload Identity webhook — AKS provisions this addon automatically when
# workload_identity_enabled=true on the cluster. Nothing to install here;
# noted for parity with the IRSA module on AWS.
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# VolumeSnapshotClass for the btrfs CSI driver
# btrfs CSI handles all snapshots (project hibernation) — Azure Disk
# snapshots are not used by the platform's snapshot path.
# -----------------------------------------------------------------------------
resource "kubectl_manifest" "btrfs_snapshot_class" {
  yaml_body = <<-YAML
    apiVersion: snapshot.storage.k8s.io/v1
    kind: VolumeSnapshotClass
    metadata:
      name: tesslate-btrfs-snapshots
      labels:
        app.kubernetes.io/name: tesslate
        app.kubernetes.io/part-of: tesslate-studio
    driver: btrfs.csi.tesslate.io
    deletionPolicy: Retain
  YAML

  depends_on = [
    time_sleep.wait_for_aks,
    helm_release.snapshot_controller,
  ]
}
