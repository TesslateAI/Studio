# =============================================================================
# Helm Releases for Tesslate Studio EKS
# =============================================================================
# Installs essential cluster components:
# - NGINX Ingress Controller (for routing)
# - cert-manager (for TLS certificates)
# - external-dns (for automatic DNS management with Cloudflare)
# - cluster-autoscaler (for automatic node scaling)
# - metrics-server (for HPA)
# =============================================================================

# -----------------------------------------------------------------------------
# NGINX Ingress Controller
# -----------------------------------------------------------------------------
resource "helm_release" "nginx_ingress" {
  name             = "ingress-nginx"
  repository       = "https://kubernetes.github.io/ingress-nginx"
  chart            = "ingress-nginx"
  version          = "4.9.0"
  namespace        = "ingress-nginx"
  create_namespace = true

  values = [
    yamlencode({
      controller = {
        replicaCount = 2

        # Use NLB for better performance with WebSockets
        service = {
          type = "LoadBalancer"
          annotations = {
            "service.beta.kubernetes.io/aws-load-balancer-type"            = "nlb"
            "service.beta.kubernetes.io/aws-load-balancer-scheme"          = "internet-facing"
            "service.beta.kubernetes.io/aws-load-balancer-nlb-target-type" = "ip"
            # Enable cross-zone load balancing
            "service.beta.kubernetes.io/aws-load-balancer-cross-zone-load-balancing-enabled" = "true"
          }
        }

        # Enable ProxyProtocol for real client IPs
        config = {
          "use-proxy-protocol"     = "false"  # Set true if using NLB proxy protocol
          "use-forwarded-headers"  = "true"
          "compute-full-forwarded-for" = "true"
          "proxy-body-size"        = "50m"
          "proxy-read-timeout"     = "3600"
          "proxy-send-timeout"     = "3600"
          # WebSocket support
          "upstream-keepalive-connections" = "10000"
          "upstream-keepalive-timeout"     = "60"
        }

        # Resources
        resources = {
          requests = {
            cpu    = "100m"
            memory = "128Mi"
          }
          limits = {
            cpu    = "500m"
            memory = "512Mi"
          }
        }

        # Metrics for monitoring
        metrics = {
          enabled = true
          serviceMonitor = {
            enabled = false  # Enable if using Prometheus Operator
          }
        }

        # Admission webhooks
        admissionWebhooks = {
          enabled = true
        }
      }
    })
  ]

  depends_on = [module.eks]
}

# -----------------------------------------------------------------------------
# cert-manager (for TLS certificates)
# -----------------------------------------------------------------------------
resource "helm_release" "cert_manager" {
  count = var.enable_cert_manager ? 1 : 0

  name             = "cert-manager"
  repository       = "https://charts.jetstack.io"
  chart            = "cert-manager"
  version          = "v1.14.0"
  namespace        = "cert-manager"
  create_namespace = true

  values = [
    yamlencode({
      installCRDs = true

      serviceAccount = {
        annotations = {
          "eks.amazonaws.com/role-arn" = module.cert_manager_irsa.iam_role_arn
        }
      }

      resources = {
        requests = {
          cpu    = "50m"
          memory = "64Mi"
        }
        limits = {
          cpu    = "200m"
          memory = "256Mi"
        }
      }

      # DNS-01 challenge configuration (for wildcard certs)
      dns01RecursiveNameservers = "1.1.1.1:53,8.8.8.8:53"
      dns01RecursiveNameserversOnly = true
    })
  ]

  depends_on = [module.eks]
}

# -----------------------------------------------------------------------------
# Cloudflare API Token Secret for cert-manager and external-dns
# -----------------------------------------------------------------------------
resource "kubernetes_namespace" "external_dns" {
  metadata {
    name = "external-dns"
  }

  depends_on = [module.eks]
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
    metadata = {
      name = "letsencrypt-prod"
    }
    spec = {
      acme = {
        server = "https://acme-v02.api.letsencrypt.org/directory"
        email  = "admin@${var.domain_name}"
        privateKeySecretRef = {
          name = "letsencrypt-prod"
        }
        solvers = [
          {
            dns01 = {
              cloudflare = {
                apiTokenSecretRef = {
                  name = "cloudflare-api-token"
                  key  = "api-token"
                }
              }
            }
            selector = {
              dnsZones = [var.domain_name]
            }
          }
        ]
      }
    }
  })

  depends_on = [
    helm_release.cert_manager,
    kubernetes_secret.cloudflare_api_token
  ]
}

# Staging issuer for testing
resource "kubectl_manifest" "letsencrypt_staging_issuer" {
  count = var.enable_cert_manager ? 1 : 0

  yaml_body = yamlencode({
    apiVersion = "cert-manager.io/v1"
    kind       = "ClusterIssuer"
    metadata = {
      name = "letsencrypt-staging"
    }
    spec = {
      acme = {
        server = "https://acme-staging-v02.api.letsencrypt.org/directory"
        email  = "admin@${var.domain_name}"
        privateKeySecretRef = {
          name = "letsencrypt-staging"
        }
        solvers = [
          {
            dns01 = {
              cloudflare = {
                apiTokenSecretRef = {
                  name = "cloudflare-api-token"
                  key  = "api-token"
                }
              }
            }
            selector = {
              dnsZones = [var.domain_name]
            }
          }
        ]
      }
    }
  })

  depends_on = [
    helm_release.cert_manager,
    kubernetes_secret.cloudflare_api_token
  ]
}

# -----------------------------------------------------------------------------
# external-dns (for automatic DNS record management)
# -----------------------------------------------------------------------------
resource "helm_release" "external_dns" {
  count = var.enable_external_dns ? 1 : 0

  name             = "external-dns"
  repository       = "https://kubernetes-sigs.github.io/external-dns"
  chart            = "external-dns"
  version          = "1.14.0"
  namespace        = "external-dns"
  create_namespace = true

  values = [
    yamlencode({
      provider = "cloudflare"

      cloudflare = {
        apiToken = ""  # Will be set via secret
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

      domainFilters = [var.domain_name]

      policy = "sync"  # sync will delete records when ingress is deleted

      sources = ["ingress", "service"]

      txtOwnerId = "${var.project_name}-${var.environment}"

      serviceAccount = {
        annotations = {
          "eks.amazonaws.com/role-arn" = module.external_dns_irsa.iam_role_arn
        }
      }

      resources = {
        requests = {
          cpu    = "50m"
          memory = "64Mi"
        }
        limits = {
          cpu    = "200m"
          memory = "256Mi"
        }
      }

      # Interval for syncing DNS records
      interval = "1m"

      # Log level
      logLevel = "info"
    })
  ]

  depends_on = [
    module.eks,
    kubernetes_secret.cloudflare_api_token_external_dns
  ]
}

# -----------------------------------------------------------------------------
# Cluster Autoscaler
# -----------------------------------------------------------------------------
resource "helm_release" "cluster_autoscaler" {
  count = var.enable_cluster_autoscaler ? 1 : 0

  name       = "cluster-autoscaler"
  repository = "https://kubernetes.github.io/autoscaler"
  chart      = "cluster-autoscaler"
  version    = "9.35.0"
  namespace  = "kube-system"

  values = [
    yamlencode({
      autoDiscovery = {
        clusterName = local.cluster_name
      }

      awsRegion = var.aws_region

      rbac = {
        serviceAccount = {
          annotations = {
            "eks.amazonaws.com/role-arn" = module.cluster_autoscaler_irsa.iam_role_arn
          }
        }
      }

      extraArgs = {
        "skip-nodes-with-local-storage"  = false
        "skip-nodes-with-system-pods"    = false
        "balance-similar-node-groups"    = true
        "expander"                       = "least-waste"
        "scale-down-delay-after-add"     = "5m"
        "scale-down-unneeded-time"       = "5m"
      }

      resources = {
        requests = {
          cpu    = "50m"
          memory = "64Mi"
        }
        limits = {
          cpu    = "200m"
          memory = "256Mi"
        }
      }
    })
  ]

  depends_on = [module.eks]
}

# -----------------------------------------------------------------------------
# Metrics Server (for HPA)
# -----------------------------------------------------------------------------
resource "helm_release" "metrics_server" {
  count = var.enable_metrics_server ? 1 : 0

  name       = "metrics-server"
  repository = "https://kubernetes-sigs.github.io/metrics-server"
  chart      = "metrics-server"
  version    = "3.12.0"
  namespace  = "kube-system"

  values = [
    yamlencode({
      args = [
        "--kubelet-insecure-tls",
        "--kubelet-preferred-address-types=InternalIP"
      ]

      resources = {
        requests = {
          cpu    = "50m"
          memory = "64Mi"
        }
        limits = {
          cpu    = "200m"
          memory = "256Mi"
        }
      }
    })
  ]

  depends_on = [module.eks]
}
