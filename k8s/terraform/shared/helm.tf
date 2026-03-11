# =============================================================================
# Helm Releases for Platform Cluster
# =============================================================================
# Infrastructure components shared by all platform tools:
# - NGINX Ingress Controller (routing)
# - cert-manager (TLS certificates via Let's Encrypt + Cloudflare DNS01)
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
        replicaCount = 1

        service = {
          type = "LoadBalancer"
          annotations = {
            "service.beta.kubernetes.io/aws-load-balancer-type"                              = "nlb"
            "service.beta.kubernetes.io/aws-load-balancer-scheme"                             = "internet-facing"
            "service.beta.kubernetes.io/aws-load-balancer-nlb-target-type"                    = "ip"
            "service.beta.kubernetes.io/aws-load-balancer-cross-zone-load-balancing-enabled"  = "true"
          }
        }

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
      }
    })
  ]

  depends_on = [module.eks]
}

# -----------------------------------------------------------------------------
# cert-manager (TLS certificates)
# -----------------------------------------------------------------------------
resource "helm_release" "cert_manager" {
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

      dns01RecursiveNameservers     = "1.1.1.1:53,8.8.8.8:53"
      dns01RecursiveNameserversOnly = true
    })
  ]

  depends_on = [module.eks]
}

# -----------------------------------------------------------------------------
# Cloudflare API Token Secret (for cert-manager DNS01 validation)
# -----------------------------------------------------------------------------
resource "kubernetes_secret" "cloudflare_api_token_cert_manager" {
  metadata {
    name      = "cloudflare-api-token"
    namespace = "cert-manager"
  }

  data = {
    api-token = var.cloudflare_api_token
  }

  depends_on = [helm_release.cert_manager]
}

# -----------------------------------------------------------------------------
# ClusterIssuer for Let's Encrypt (Cloudflare DNS-01)
# -----------------------------------------------------------------------------
resource "kubectl_manifest" "letsencrypt_issuer" {
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
                email = "admin@${var.domain_name}"
                apiTokenSecretRef = {
                  name = "cloudflare-api-token"
                  key  = "api-token"
                }
              }
            }
            selector = {
              dnsZones = [var.cloudflare_zone_name]
            }
          }
        ]
      }
    }
  })

  depends_on = [
    helm_release.cert_manager,
    kubernetes_secret.cloudflare_api_token_cert_manager
  ]
}
