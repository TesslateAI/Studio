# =============================================================================
# Kubernetes Resources for OpenSail (Azure AKS)
# =============================================================================
# Mirrors k8s/terraform/aws/kubernetes.tf. Only the Service Account annotations
# differ — AKS Workload Identity uses
#   azure.workload.identity/client-id: <uami client id>
# instead of EKS IRSA's eks.amazonaws.com/role-arn.
# =============================================================================

# -----------------------------------------------------------------------------
# PriorityClasses (cluster-scoped) — same shape as the AWS stack
# -----------------------------------------------------------------------------
resource "kubernetes_priority_class" "system" {
  metadata { name = "tesslate-system" }

  value             = 2000
  global_default    = false
  preemption_policy = "PreemptLowerPriority"
  description       = "Tesslate system-level pods (CSI driver, Volume Hub). Never preempted."

  depends_on = [time_sleep.wait_for_aks]
}

resource "kubernetes_priority_class" "ephemeral" {
  metadata { name = "tesslate-ephemeral" }

  value             = 1000
  global_default    = false
  preemption_policy = "PreemptLowerPriority"
  description       = "Tesslate ephemeral pods (one-shot commands, terminal). Can preempt environment pods."

  depends_on = [time_sleep.wait_for_aks]
}

resource "kubernetes_priority_class" "environment" {
  metadata { name = "tesslate-environment" }

  value             = 100
  global_default    = false
  preemption_policy = "PreemptLowerPriority"
  description       = "Tesslate environment pods (dev containers, services). Lowest Tesslate priority."

  depends_on = [time_sleep.wait_for_aks]
}

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

  lifecycle {
    ignore_changes = [metadata[0].labels]
  }

  depends_on = [time_sleep.wait_for_aks]
}

# -----------------------------------------------------------------------------
# Service Account for Tesslate Backend (Workload Identity)
# -----------------------------------------------------------------------------
resource "kubernetes_service_account" "tesslate_backend" {
  metadata {
    name      = "tesslate-backend-sa"
    namespace = kubernetes_namespace.tesslate.metadata[0].name

    annotations = {
      "azure.workload.identity/client-id" = azurerm_user_assigned_identity.backend.client_id
      "azure.workload.identity/tenant-id" = data.azurerm_client_config.current.tenant_id
    }

    labels = {
      "app.kubernetes.io/name"      = "tesslate-backend"
      "app.kubernetes.io/component" = "backend"
      "azure.workload.identity/use" = "true"
    }
  }

  lifecycle {
    ignore_changes = [metadata[0].labels]
  }
}

# -----------------------------------------------------------------------------
# Service Account for btrfs CSI Node (Workload Identity)
# -----------------------------------------------------------------------------
resource "kubernetes_service_account" "btrfs_csi_node" {
  metadata {
    name      = "tesslate-btrfs-csi-node"
    namespace = "kube-system"

    annotations = {
      "azure.workload.identity/client-id" = azurerm_user_assigned_identity.btrfs_csi.client_id
      "azure.workload.identity/tenant-id" = data.azurerm_client_config.current.tenant_id
    }

    labels = {
      "app"                         = "tesslate-btrfs-csi-node"
      "azure.workload.identity/use" = "true"
    }
  }

  lifecycle {
    ignore_changes = [metadata[0].labels]
  }

  depends_on = [time_sleep.wait_for_aks]
}

# -----------------------------------------------------------------------------
# Volume Hub ServiceAccount (Workload Identity)
# -----------------------------------------------------------------------------
resource "kubernetes_service_account" "volume_hub" {
  metadata {
    name      = "tesslate-volume-hub"
    namespace = "kube-system"

    annotations = {
      "azure.workload.identity/client-id" = azurerm_user_assigned_identity.volume_hub.client_id
      "azure.workload.identity/tenant-id" = data.azurerm_client_config.current.tenant_id
    }

    labels = {
      "app.kubernetes.io/name"      = "tesslate-volume-hub"
      "azure.workload.identity/use" = "true"
    }
  }

  lifecycle {
    ignore_changes = [metadata[0].labels]
  }

  depends_on = [time_sleep.wait_for_aks]
}

# -----------------------------------------------------------------------------
# btrfs CSI Config Secret — Azure Blob via the S3-compatible endpoint.
# The rclone S3 path works against Azure Blob via the Storage Account's
# S3-compatible endpoint (preview/GA depending on region). For regions
# without S3 compat, set storage_provider=azureblob and the corresponding
# RCLONE_AZUREBLOB_* env vars — the driver supports both paths.
# -----------------------------------------------------------------------------
resource "kubernetes_secret" "btrfs_csi_config" {
  metadata {
    name      = "tesslate-btrfs-csi-config"
    namespace = "kube-system"
  }

  data = {
    STORAGE_PROVIDER   = "s3"
    STORAGE_BUCKET     = azurerm_storage_container.btrfs_snapshots.name
    RCLONE_S3_PROVIDER = "Other" # not AWS — disables AWS-specific signing quirks
    RCLONE_S3_REGION   = var.azure_region
    # Azure Blob S3-compatible endpoint. Workload Identity supplies the
    # bearer token via the AAD federation flow; the static keys are left
    # empty for the same reason they're empty on EKS+IRSA.
    RCLONE_S3_ENDPOINT           = "https://${azurerm_storage_account.this.name}.blob.core.windows.net"
    RCLONE_S3_ACCESS_KEY_ID      = ""
    RCLONE_S3_SECRET_ACCESS_KEY  = ""
    RCLONE_S3_ENV_AUTH           = "true"
    RCLONE_S3_NO_CHECK_BUCKET    = "true"
    SYNC_INTERVAL                = "60"
    POOL_PATH                    = "/mnt/tesslate-pool"
    ORCHESTRATOR_INTERNAL_SECRET = var.internal_api_secret
  }

  type = "Opaque"

  depends_on = [time_sleep.wait_for_aks]
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
    POSTGRES_DB       = var.create_postgres ? var.postgres_database_name : "tesslate"
    POSTGRES_USER     = var.create_postgres ? var.postgres_admin_username : "tesslate_user"
    POSTGRES_PASSWORD = var.postgres_password
  }

  type = "Opaque"
}

# -----------------------------------------------------------------------------
# S3 Credentials Secret — Azure Blob via S3-compat endpoint.
# Workload Identity carries auth, static keys are left blank.
# -----------------------------------------------------------------------------
resource "kubernetes_secret" "s3_credentials" {
  metadata {
    name      = "s3-credentials"
    namespace = kubernetes_namespace.tesslate.metadata[0].name
  }

  data = {
    S3_ACCESS_KEY_ID     = "" # Not needed with Workload Identity
    S3_SECRET_ACCESS_KEY = "" # Not needed with Workload Identity
    S3_BUCKET_NAME       = azurerm_storage_container.projects.name
    # Non-empty endpoint switches the boto3 client off native AWS signing.
    S3_ENDPOINT_URL = "https://${azurerm_storage_account.this.name}.blob.core.windows.net"
    S3_REGION       = var.azure_region
  }

  type = "Opaque"
}

# -----------------------------------------------------------------------------
# Llama API credentials — shared by seeded Tesslate Apps that call an
# OpenAI-compatible LLM gateway directly.
# -----------------------------------------------------------------------------
resource "kubernetes_secret" "llama_api_credentials" {
  metadata {
    name      = "llama-api-credentials"
    namespace = kubernetes_namespace.tesslate.metadata[0].name
  }

  data = {
    api_key = var.llama_api_key
  }

  type = "Opaque"
}

# -----------------------------------------------------------------------------
# Application Secrets
# -----------------------------------------------------------------------------
locals {
  # Composes a Postgres DSN whether we're using the managed flexible server
  # or the in-cluster postgres pod. Mirrors aws/kubernetes.tf.
  postgres_host = var.create_postgres ? "${azurerm_postgresql_flexible_server.this[0].name}.${azurerm_private_dns_zone.postgres[0].name}" : "postgres:5432"
  postgres_user = var.create_postgres ? var.postgres_admin_username : "tesslate_user"

  database_url = var.create_postgres ? (
    "postgresql+asyncpg://${local.postgres_user}:${var.postgres_password}@${local.postgres_host}/${var.postgres_database_name}?ssl=require"
    ) : (
    "postgresql+asyncpg://${local.postgres_user}:${var.postgres_password}@${local.postgres_host}/tesslate"
  )

  marketplace_database_url = var.create_postgres ? (
    "postgresql+asyncpg://${local.postgres_user}:${var.postgres_password}@${local.postgres_host}/tesslate_marketplace?ssl=require"
    ) : (
    "postgresql+asyncpg://${local.postgres_user}:${var.postgres_password}@${local.postgres_host}/tesslate_marketplace"
  )

  marketplace_admin_database_url = var.create_postgres ? (
    "postgresql://${local.postgres_user}:${var.postgres_password}@${local.postgres_host}/postgres?sslmode=require"
    ) : (
    "postgresql://${local.postgres_user}:${var.postgres_password}@${local.postgres_host}/postgres"
  )

  redis_url = var.create_redis ? (
    "rediss://:${azurerm_redis_cache.this[0].primary_access_key}@${azurerm_redis_cache.this[0].hostname}:${azurerm_redis_cache.this[0].ssl_port}/0"
    ) : (
    "redis://redis:6379/0"
  )
}

resource "kubernetes_secret" "app_secrets" {
  metadata {
    name      = "tesslate-app-secrets"
    namespace = kubernetes_namespace.tesslate.metadata[0].name
  }

  data = {
    SECRET_KEY   = var.app_secret_key
    DATABASE_URL = local.database_url

    # LiteLLM
    LITELLM_API_BASE       = "http://litellm-service.tesslate.svc.cluster.local:4000/v1"
    LITELLM_MASTER_KEY     = var.litellm_master_key
    LITELLM_DEFAULT_MODELS = var.litellm_default_models
    LITELLM_TEAM_ID        = "default"
    LITELLM_EMAIL_DOMAIN   = var.domain_name
    LITELLM_INITIAL_BUDGET = "10000.0"

    # CORS & Domain
    CORS_ORIGINS        = "https://${var.domain_name},https://*.${var.domain_name}"
    ALLOWED_HOSTS       = "${var.domain_name},*.${var.domain_name}"
    APP_DOMAIN          = var.domain_name
    APP_BASE_URL        = "https://${var.domain_name}"
    DEV_SERVER_BASE_URL = "https://*.${var.domain_name}"
    COOKIE_DOMAIN       = ".${var.domain_name}"

    # K8s config — devserver image lives in ACR
    K8S_DEVSERVER_IMAGE = "${local.acr_devserver_url}:${local.image_tag}"
    K8S_REGISTRY_URL    = local.acr_login_server

    # Tesslate Apps registry prefix — overlay reads this through envFrom
    APP_IMAGE_REGISTRY_PREFIX = local.acr_login_server

    # OAuth - Google
    GOOGLE_CLIENT_ID          = var.google_client_id
    GOOGLE_CLIENT_SECRET      = var.google_client_secret
    GOOGLE_OAUTH_REDIRECT_URI = "https://${var.domain_name}/api/auth/google/callback"
    GOOGLE_OAUTH_ENABLED      = tostring(var.google_oauth_enabled)

    # OAuth - GitHub
    GITHUB_CLIENT_ID          = var.github_client_id
    GITHUB_CLIENT_SECRET      = var.github_client_secret
    GITHUB_OAUTH_REDIRECT_URI = "https://${var.domain_name}/api/auth/github/callback"
    GITHUB_OAUTH_ENABLED      = tostring(var.github_oauth_enabled)

    # Stripe
    STRIPE_SECRET_KEY            = var.stripe_secret_key
    STRIPE_PUBLISHABLE_KEY       = var.stripe_publishable_key
    STRIPE_WEBHOOK_SECRET        = var.stripe_webhook_secret
    STRIPE_CONNECT_CLIENT_ID     = var.stripe_connect_client_id
    STRIPE_BASIC_PRICE_ID        = var.stripe_basic_price_id
    STRIPE_PRO_PRICE_ID          = var.stripe_pro_price_id
    STRIPE_ULTRA_PRICE_ID        = var.stripe_ultra_price_id
    STRIPE_BASIC_ANNUAL_PRICE_ID = var.stripe_basic_annual_price_id
    STRIPE_PRO_ANNUAL_PRICE_ID   = var.stripe_pro_annual_price_id
    STRIPE_ULTRA_ANNUAL_PRICE_ID = var.stripe_ultra_annual_price_id

    # Deployment Providers
    VERCEL_CLIENT_ID                = var.vercel_client_id
    VERCEL_CLIENT_SECRET            = var.vercel_client_secret
    VERCEL_OAUTH_REDIRECT_URI       = "https://${var.domain_name}/api/deployment-oauth/vercel/callback"
    NETLIFY_CLIENT_ID               = var.netlify_client_id
    NETLIFY_CLIENT_SECRET           = var.netlify_client_secret
    NETLIFY_OAUTH_REDIRECT_URI      = "https://${var.domain_name}/api/deployment-oauth/netlify/callback"
    HEROKU_CLIENT_ID                = var.heroku_client_id
    HEROKU_CLIENT_SECRET            = var.heroku_client_secret
    HEROKU_OAUTH_REDIRECT_URI       = "https://${var.domain_name}/api/deployment-oauth/heroku/callback"
    DIGITALOCEAN_CLIENT_ID          = var.digitalocean_client_id
    DIGITALOCEAN_CLIENT_SECRET      = var.digitalocean_client_secret
    DIGITALOCEAN_OAUTH_REDIRECT_URI = "https://${var.domain_name}/api/deployment-oauth/digitalocean/callback"

    # MCP Connector OAuth Apps
    MCP_OAUTH_APP_GITHUB_CLIENT_ID     = var.mcp_oauth_app_github_client_id
    MCP_OAUTH_APP_GITHUB_CLIENT_SECRET = var.mcp_oauth_app_github_client_secret
    MCP_OAUTH_APP_SLACK_CLIENT_ID      = var.mcp_oauth_app_slack_client_id
    MCP_OAUTH_APP_SLACK_CLIENT_SECRET  = var.mcp_oauth_app_slack_client_secret

    # Container Push Configuration
    KANIKO_IMAGE                  = var.kaniko_image
    CONTAINER_PUSH_TIMEOUT        = tostring(var.container_push_timeout)
    CONTAINER_PUSH_DEFAULT_CPU    = var.container_push_default_cpu
    CONTAINER_PUSH_DEFAULT_MEMORY = var.container_push_default_memory

    # Deployment credential encryption
    DEPLOYMENT_ENCRYPTION_KEY = var.deployment_encryption_key

    # SMTP
    SMTP_HOST         = var.smtp_host
    SMTP_PORT         = tostring(var.smtp_port)
    SMTP_USERNAME     = var.smtp_username
    SMTP_PASSWORD     = var.smtp_password
    SMTP_USE_TLS      = tostring(var.smtp_use_tls)
    SMTP_SENDER_EMAIL = var.smtp_sender_email
    TWO_FA_ENABLED    = tostring(var.two_fa_enabled)

    # PostHog
    POSTHOG_KEY = var.posthog_key

    # Database SSL — enabled when using managed Postgres
    DATABASE_SSL = tostring(var.create_postgres)

    # Email compliance
    ALLOWED_EMAIL_DOMAINS = var.allowed_email_domains
    BLOCKED_EMAIL_DOMAINS = var.blocked_email_domains

    # Discord notifications
    DISCORD_WEBHOOK_URL = var.discord_webhook_url

    # Redis
    REDIS_URL = local.redis_url

    # Internal API shared secret
    INTERNAL_API_SECRET = var.internal_api_secret

    # Federated marketplace
    MARKETPLACE_ADMIN_TOKEN    = random_password.marketplace_admin_token.result
    TESSLATE_OFFICIAL_BASE_URL = "http://tesslate-marketplace:8800"
  }

  type = "Opaque"
}

# -----------------------------------------------------------------------------
# Marketplace Secret
# -----------------------------------------------------------------------------
resource "random_password" "marketplace_bundle_url_secret" {
  length  = 48
  special = false
}

resource "random_password" "marketplace_admin_token" {
  length  = 48
  special = false
}

resource "kubernetes_secret" "marketplace_secret" {
  metadata {
    name      = "marketplace-secret"
    namespace = kubernetes_namespace.tesslate.metadata[0].name
  }

  data = {
    DATABASE_URL       = local.marketplace_database_url
    ADMIN_DATABASE_URL = local.marketplace_admin_database_url
    BUNDLE_URL_SECRET  = random_password.marketplace_bundle_url_secret.result
    STATIC_TOKENS      = "${random_password.marketplace_admin_token.result}:admin.write:publish:yanks.write:catalog.write:pricing.write"
    S3_BUCKET          = azurerm_storage_container.marketplace_bundles.name
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
    DEPLOYMENT_MODE             = "kubernetes"
    K8S_NAMESPACE_PER_PROJECT   = "true"
    K8S_ENABLE_NETWORK_POLICIES = "true"
    K8S_INGRESS_DOMAIN          = var.domain_name
    K8S_STORAGE_CLASS           = "tesslate-block-storage"
    K8S_INGRESS_CLASS           = "nginx"
    devserver_image             = "${local.acr_devserver_url}:${local.image_tag}"
    registry_url                = local.acr_login_server
    azure_region                = var.azure_region
    storage_account_name        = azurerm_storage_account.this.name
    projects_container_name     = azurerm_storage_container.projects.name
  }
}

# -----------------------------------------------------------------------------
# Frontend ConfigMap (Runtime Configuration)
# -----------------------------------------------------------------------------
resource "kubernetes_config_map" "frontend_config" {
  metadata {
    name      = "frontend-config"
    namespace = kubernetes_namespace.tesslate.metadata[0].name
  }

  data = {
    api-url      = "https://${var.domain_name}"
    posthog-host = var.posthog_host
  }
}

# -----------------------------------------------------------------------------
# Wildcard TLS Certificate (cert-manager + Cloudflare DNS01)
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
      secretTemplate = {
        annotations = {
          "reflector.v1.k8s.emberstack.com/reflection-allowed"            = "true"
          "reflector.v1.k8s.emberstack.com/reflection-allowed-namespaces" = "proj-.*"
          "reflector.v1.k8s.emberstack.com/reflection-auto-enabled"       = "true"
          "reflector.v1.k8s.emberstack.com/reflection-auto-namespaces"    = "proj-.*"
        }
      }
      issuerRef = {
        name = "letsencrypt-prod"
        kind = "ClusterIssuer"
      }
      commonName = var.domain_name
      dnsNames = [
        var.domain_name,
        "*.${var.domain_name}",
      ]
    }
  })

  depends_on = [
    kubernetes_namespace.tesslate,
    kubectl_manifest.letsencrypt_issuer,
  ]
}

# -----------------------------------------------------------------------------
# Main Application Ingress
# -----------------------------------------------------------------------------
resource "kubectl_manifest" "tesslate_ingress" {
  yaml_body = yamlencode({
    apiVersion = "networking.k8s.io/v1"
    kind       = "Ingress"
    metadata = {
      name      = "tesslate-ingress"
      namespace = "tesslate"
      annotations = {
        "kubernetes.io/ingress.class"                        = "nginx"
        "cert-manager.io/cluster-issuer"                     = "letsencrypt-prod"
        "nginx.ingress.kubernetes.io/ssl-redirect"           = "true"
        "nginx.ingress.kubernetes.io/force-ssl-redirect"     = "true"
        "nginx.ingress.kubernetes.io/proxy-http-version"     = "1.1"
        "nginx.ingress.kubernetes.io/proxy-read-timeout"     = "3600"
        "nginx.ingress.kubernetes.io/proxy-send-timeout"     = "3600"
        "nginx.ingress.kubernetes.io/proxy-connect-timeout"  = "3600"
        "nginx.ingress.kubernetes.io/proxy-body-size"        = "100m"
        "nginx.ingress.kubernetes.io/proxy-buffering"        = "off"
        "nginx.ingress.kubernetes.io/use-regex"              = "true"
        "nginx.ingress.kubernetes.io/enable-cors"            = "true"
        "nginx.ingress.kubernetes.io/cors-allow-origin"      = "https://${var.domain_name}, https://*.${var.domain_name}"
        "nginx.ingress.kubernetes.io/cors-allow-methods"     = "GET, PUT, POST, DELETE, PATCH, OPTIONS"
        "nginx.ingress.kubernetes.io/cors-allow-credentials" = "true"
        "nginx.ingress.kubernetes.io/proxy-hide-header"      = "X-Powered-By"
        "nginx.ingress.kubernetes.io/affinity"               = "cookie"
        "nginx.ingress.kubernetes.io/session-cookie-name"    = "TESS_AFFINITY"
        "nginx.ingress.kubernetes.io/session-cookie-max-age" = "7200"
        "nginx.ingress.kubernetes.io/session-cookie-path"    = "/"
      }
    }
    spec = {
      ingressClassName = "nginx"
      tls = [{
        hosts      = [var.domain_name, "*.${var.domain_name}"]
        secretName = "tesslate-wildcard-tls"
      }]
      rules = [{
        host = var.domain_name
        http = {
          paths = [
            { path = "/api", pathType = "Prefix", backend = { service = { name = "tesslate-backend-service", port = { number = 8000 } } } },
            { path = "/ws", pathType = "Prefix", backend = { service = { name = "tesslate-backend-service", port = { number = 8000 } } } },
            { path = "/health", pathType = "Prefix", backend = { service = { name = "tesslate-backend-service", port = { number = 8000 } } } },
            { path = "/", pathType = "Prefix", backend = { service = { name = "tesslate-frontend-service", port = { number = 80 } } } },
          ]
        }
      }]
    }
  })

  depends_on = [
    kubernetes_namespace.tesslate,
    kubectl_manifest.wildcard_certificate,
    # nginx admission webhook isn't reliable until the controller pods are
    # actually serving — by the time the LB has an IP, the controller is
    # past Ready, so this gate also gates webhook readiness.
    null_resource.wait_for_lb_ip,
  ]
}

# -----------------------------------------------------------------------------
# Default NetworkPolicy for the tesslate namespace
# -----------------------------------------------------------------------------
resource "kubernetes_network_policy" "tesslate_default" {
  metadata {
    name      = "tesslate-default-policy"
    namespace = kubernetes_namespace.tesslate.metadata[0].name
  }

  spec {
    pod_selector {}
    policy_types = ["Ingress", "Egress"]

    ingress {
      from {
        namespace_selector {
          match_labels = {
            "kubernetes.io/metadata.name" = "ingress-nginx"
          }
        }
      }
    }

    ingress {
      from {
        pod_selector {}
      }
    }

    egress {
      to {
        ip_block {
          cidr = "0.0.0.0/0"
        }
      }
    }
  }
}
