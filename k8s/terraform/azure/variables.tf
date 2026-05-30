# =============================================================================
# Terraform Variables for OpenSail Azure AKS
# =============================================================================
# Mirrors k8s/terraform/aws/variables.tf so the same tfvars structure works
# across both clouds. Azure-specific knobs (azure_region, aks_*, postgres_*,
# acr_*) replace their AWS counterparts; everything else (app secrets, OAuth
# config, Stripe, SMTP, etc.) is shared verbatim.
# =============================================================================

# -----------------------------------------------------------------------------
# General Settings
# -----------------------------------------------------------------------------
variable "project_name" {
  description = "Name of the project (used for resource naming)"
  type        = string
  default     = "tesslate"
}

variable "environment" {
  description = "Environment name (e.g., production, beta)"
  type        = string
  default     = "production"
}

variable "azure_region" {
  description = "Azure region to deploy resources (e.g., eastus, westus2)"
  type        = string
  default     = "eastus"
}

# -----------------------------------------------------------------------------
# Image Configuration
# -----------------------------------------------------------------------------
variable "image_tag" {
  description = "Container image tag for ACR images (defaults to environment name if empty)"
  type        = string
  default     = ""
}

# -----------------------------------------------------------------------------
# Domain Configuration
# -----------------------------------------------------------------------------
variable "domain_name" {
  description = "Primary domain name (e.g., opensail.tesslate.com)"
  type        = string
}

variable "wildcard_domain" {
  description = "Wildcard domain for user projects (e.g., *.opensail.tesslate.com)"
  type        = string
  default     = ""
}

# -----------------------------------------------------------------------------
# Cloudflare Configuration (for cert-manager DNS01 + DNS records)
# -----------------------------------------------------------------------------
variable "cloudflare_api_token" {
  description = "Cloudflare API token for DNS management"
  type        = string
  sensitive   = true
}

variable "cloudflare_zone_id" {
  description = "Cloudflare Zone ID for the domain"
  type        = string
  default     = ""
}

variable "cloudflare_zone_name" {
  description = "Cloudflare zone name (must match the actual Cloudflare zone, not a subdomain)"
  type        = string
  default     = ""
}

# -----------------------------------------------------------------------------
# VNet Configuration
# -----------------------------------------------------------------------------
variable "vnet_cidr" {
  description = "CIDR block for the VNet"
  type        = string
  default     = "10.0.0.0/16"
}

variable "aks_subnet_cidr" {
  description = "CIDR for the AKS node subnet"
  type        = string
  default     = "10.0.0.0/20"
}

variable "postgres_subnet_cidr" {
  description = "CIDR for the delegated PostgreSQL Flexible Server subnet"
  type        = string
  default     = "10.0.16.0/24"
}

variable "redis_subnet_cidr" {
  description = "CIDR for the Azure Cache for Redis subnet"
  type        = string
  default     = "10.0.17.0/24"
}

# -----------------------------------------------------------------------------
# AKS Configuration
# -----------------------------------------------------------------------------
variable "aks_cluster_version" {
  description = "Kubernetes version for AKS cluster (must be currently supported in the region — check `az aks get-versions --location <region>`)"
  type        = string
  default     = "1.33"
}

variable "aks_system_node_vm_size" {
  description = "VM size for the AKS system node pool (CoreDNS, kube-proxy, metrics-server)"
  type        = string
  default     = "Standard_D2s_v5"
}

variable "aks_system_node_count" {
  description = "Number of nodes in the AKS system node pool"
  type        = number
  default     = 2
}

variable "aks_user_node_vm_size" {
  description = "VM size for the AKS user (primary workload) node pool"
  type        = string
  default     = "Standard_D4s_v5"
}

variable "aks_user_node_count" {
  description = "Desired number of nodes in the AKS user node pool"
  type        = number
  default     = 2
}

variable "aks_user_node_min_count" {
  description = "Minimum number of nodes in the AKS user node pool"
  type        = number
  default     = 1
}

variable "aks_user_node_max_count" {
  description = "Maximum number of nodes in the AKS user node pool"
  type        = number
  default     = 5
}

variable "aks_user_node_disk_size_gb" {
  description = "OS disk size (GB) for AKS user nodes"
  type        = number
  default     = 100
}

variable "aks_spot_node_vm_size" {
  description = "VM size for the AKS spot node pool (user-project workloads)"
  type        = string
  default     = "Standard_D4s_v5"
}

variable "aks_spot_node_count" {
  description = "Desired number of spot nodes (set 0 to skip the spot pool)"
  type        = number
  default     = 1
}

variable "aks_spot_node_max_count" {
  description = "Maximum number of spot nodes"
  type        = number
  default     = 10
}

variable "aks_spot_max_price" {
  description = "Maximum hourly price (USD) for AKS spot VMs. -1 = pay up to the on-demand price."
  type        = number
  default     = -1
}

# -----------------------------------------------------------------------------
# Storage Account Configuration (Blob — projects / snapshots / bundles)
# -----------------------------------------------------------------------------
variable "storage_account_tier" {
  description = "Storage account tier (Standard / Premium)"
  type        = string
  default     = "Standard"
}

variable "storage_account_replication" {
  description = "Storage account replication (LRS / ZRS / GRS / RAGRS)"
  type        = string
  default     = "LRS"
}

variable "storage_force_destroy" {
  description = "Allow the storage account to be destroyed even if it contains data"
  type        = bool
  default     = false
}

# -----------------------------------------------------------------------------
# Database Configuration (Azure Database for PostgreSQL Flexible Server)
# -----------------------------------------------------------------------------
variable "create_postgres" {
  description = "Create an Azure Postgres Flexible Server (false = use K8s-managed postgres)"
  type        = bool
  default     = false
}

variable "postgres_sku_name" {
  description = "Postgres Flexible Server SKU (e.g. B_Standard_B1ms, GP_Standard_D2s_v3)"
  type        = string
  default     = "B_Standard_B2ms"
}

variable "postgres_version" {
  description = "Postgres major version"
  type        = string
  default     = "15"
}

variable "postgres_storage_mb" {
  description = "Postgres storage in MB (must be one of Azure's allowed sizes)"
  type        = number
  default     = 32768
}

variable "postgres_database_name" {
  description = "Postgres database name"
  type        = string
  default     = "tesslate"
}

variable "postgres_admin_username" {
  description = "Postgres administrator username"
  type        = string
  default     = "tesslate_admin"
}

# -----------------------------------------------------------------------------
# Application Secrets (passed to K8s)
# -----------------------------------------------------------------------------
variable "postgres_password" {
  description = "PostgreSQL password (used by RDS-equivalent + K8s postgres)"
  type        = string
  sensitive   = true
}

variable "app_secret_key" {
  description = "Application secret key for JWT signing"
  type        = string
  sensitive   = true
}

variable "internal_api_secret" {
  description = "Shared secret for cluster-internal /api/internal/* endpoints (Hub GC, btrfs CSI)"
  type        = string
  sensitive   = true
}

variable "litellm_api_base" {
  description = "DEPRECATED: LiteLLM is now self-hosted. Kept for backward compatibility."
  type        = string
  default     = ""
}

variable "litellm_master_key" {
  description = "LiteLLM master API key"
  type        = string
  sensitive   = true
  default     = ""
}

variable "litellm_default_models" {
  description = "Default LiteLLM models (comma-separated)"
  type        = string
  default     = "claude-sonnet-4.6,claude-opus-4.6"
}

variable "google_client_id" {
  description = "Google OAuth client ID"
  type        = string
  default     = ""
}

variable "google_client_secret" {
  description = "Google OAuth client secret"
  type        = string
  sensitive   = true
  default     = ""
}

variable "github_client_id" {
  description = "GitHub OAuth client ID"
  type        = string
  default     = ""
}

variable "github_client_secret" {
  description = "GitHub OAuth client secret"
  type        = string
  sensitive   = true
  default     = ""
}

variable "google_oauth_enabled" {
  description = "Enable Google OAuth login"
  type        = bool
  default     = false
}

variable "github_oauth_enabled" {
  description = "Enable GitHub OAuth login"
  type        = bool
  default     = false
}

variable "stripe_secret_key" {
  description = "Stripe secret key"
  type        = string
  sensitive   = true
  default     = ""
}

variable "stripe_webhook_secret" {
  description = "Stripe webhook secret"
  type        = string
  sensitive   = true
  default     = ""
}

variable "stripe_publishable_key" {
  description = "Stripe publishable key"
  type        = string
  default     = ""
}

variable "stripe_connect_client_id" {
  description = "Stripe Connect client ID for marketplace payouts"
  type        = string
  sensitive   = true
  default     = ""
}

variable "stripe_basic_price_id" {
  description = "Stripe price ID for Basic tier (monthly)"
  type        = string
  default     = ""
}

variable "stripe_pro_price_id" {
  description = "Stripe price ID for Pro tier (monthly)"
  type        = string
  default     = ""
}

variable "stripe_ultra_price_id" {
  description = "Stripe price ID for Ultra tier (monthly)"
  type        = string
  default     = ""
}

variable "stripe_basic_annual_price_id" {
  description = "Stripe price ID for Basic tier (annual)"
  type        = string
  default     = ""
}

variable "stripe_pro_annual_price_id" {
  description = "Stripe price ID for Pro tier (annual)"
  type        = string
  default     = ""
}

variable "stripe_ultra_annual_price_id" {
  description = "Stripe price ID for Ultra tier (annual)"
  type        = string
  default     = ""
}

# -----------------------------------------------------------------------------
# Deployment Provider OAuth (Vercel, Netlify, Heroku, DigitalOcean)
# -----------------------------------------------------------------------------
variable "vercel_client_id" {
  type    = string
  default = ""
}

variable "vercel_client_secret" {
  type      = string
  sensitive = true
  default   = ""
}

variable "netlify_client_id" {
  type    = string
  default = ""
}

variable "netlify_client_secret" {
  type      = string
  sensitive = true
  default   = ""
}

variable "heroku_client_id" {
  type    = string
  default = ""
}

variable "heroku_client_secret" {
  type      = string
  sensitive = true
  default   = ""
}

variable "digitalocean_client_id" {
  type    = string
  default = ""
}

variable "digitalocean_client_secret" {
  type      = string
  sensitive = true
  default   = ""
}

variable "deployment_encryption_key" {
  description = "Base64-encoded Fernet key for encrypting deployment OAuth tokens (falls back to app_secret_key if empty)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "mcp_oauth_app_github_client_id" {
  type    = string
  default = ""
}

variable "mcp_oauth_app_github_client_secret" {
  type      = string
  sensitive = true
  default   = ""
}

variable "mcp_oauth_app_slack_client_id" {
  type    = string
  default = ""
}

variable "mcp_oauth_app_slack_client_secret" {
  type      = string
  sensitive = true
  default   = ""
}

variable "kaniko_image" {
  description = "Kaniko executor image for container builds"
  type        = string
  default     = "gcr.io/kaniko-project/executor:latest"
}

variable "container_push_timeout" {
  description = "Timeout in seconds for container image export + push + deploy"
  type        = number
  default     = 900
}

variable "container_push_default_cpu" {
  description = "Default CPU allocation for container-push deployments"
  type        = string
  default     = "0.25"
}

variable "container_push_default_memory" {
  description = "Default memory allocation for container-push deployments"
  type        = string
  default     = "512Mi"
}

# -----------------------------------------------------------------------------
# SMTP Configuration (Email / 2FA)
# -----------------------------------------------------------------------------
variable "smtp_host" {
  type    = string
  default = ""
}

variable "smtp_port" {
  type    = number
  default = 587
}

variable "smtp_username" {
  type      = string
  default   = ""
  sensitive = true
}

variable "smtp_password" {
  type      = string
  default   = ""
  sensitive = true
}

variable "smtp_use_tls" {
  type    = bool
  default = true
}

variable "smtp_sender_email" {
  type    = string
  default = ""
}

variable "two_fa_enabled" {
  type    = bool
  default = false
}

# -----------------------------------------------------------------------------
# Feature Flags
# -----------------------------------------------------------------------------
variable "enable_cluster_autoscaler" {
  type    = bool
  default = true
}

variable "enable_metrics_server" {
  type    = bool
  default = true
}

variable "enable_external_dns" {
  type    = bool
  default = true
}

variable "enable_cert_manager" {
  type    = bool
  default = true
}

variable "cert_alert_webhook_url" {
  description = "Webhook URL for cert-monitor CronJob (Slack/Discord/Mattermost). Empty disables webhook delivery."
  type        = string
  default     = ""
  sensitive   = true
}

# -----------------------------------------------------------------------------
# Frontend Configuration
# -----------------------------------------------------------------------------
variable "posthog_host" {
  description = "PostHog analytics host URL"
  type        = string
  default     = "https://app.posthog.com"
}

variable "posthog_key" {
  description = "PostHog project API key"
  type        = string
  sensitive   = true
  default     = ""
}

# -----------------------------------------------------------------------------
# Email Compliance
# -----------------------------------------------------------------------------
variable "allowed_email_domains" {
  type    = string
  default = ""
}

variable "blocked_email_domains" {
  type    = string
  default = ""
}

# -----------------------------------------------------------------------------
# Discord Notifications
# -----------------------------------------------------------------------------
variable "discord_webhook_url" {
  description = "Discord webhook URL for signup/login notifications (empty = disabled)"
  type        = string
  sensitive   = true
  default     = ""
}

# -----------------------------------------------------------------------------
# LiteLLM Self-Hosted Deployment
# -----------------------------------------------------------------------------
variable "litellm_create_postgres" {
  description = "Use Azure Postgres for LiteLLM database (false = K8s-managed PostgreSQL)"
  type        = bool
  default     = false
}

variable "litellm_postgres_sku_name" {
  description = "Postgres SKU for LiteLLM database"
  type        = string
  default     = "B_Standard_B1ms"
}

variable "litellm_postgres_storage_mb" {
  description = "Postgres storage for LiteLLM (MB)"
  type        = number
  default     = 32768
}

variable "litellm_db_password" {
  description = "PostgreSQL password for LiteLLM database"
  type        = string
  sensitive   = true
  default     = ""
}

variable "litellm_image_tag" {
  description = "LiteLLM Docker image tag"
  type        = string
  default     = "main-v1.81.9-stable"
}

variable "litellm_public_access" {
  description = "Expose LiteLLM publicly via ingress at litellm.{domain}"
  type        = bool
  default     = false
}

variable "bedrock_api_key" {
  description = "AWS Bedrock API key (bearer token) for LiteLLM proxy"
  type        = string
  sensitive   = true
  default     = ""
}

variable "bedrock_aws_region" {
  description = "AWS region for Bedrock API (can differ from deployment region)"
  type        = string
  default     = "us-east-1"
}

variable "vertex_project" {
  type    = string
  default = ""
}

variable "vertex_location" {
  type    = string
  default = "us-central1"
}

variable "vertex_credentials" {
  type      = string
  sensitive = true
  default   = ""
}

variable "nanogpt_api_key" {
  description = "NanoGPT API key for OpenAI-compatible gateway"
  type        = string
  sensitive   = true
  default     = ""
}

variable "azure_api_key" {
  description = "Azure OpenAI API key (for LiteLLM proxy — distinct from the deployment subscription)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "azure_api_base" {
  description = "Azure OpenAI endpoint URL (e.g. https://your-resource.openai.azure.com)"
  type        = string
  default     = ""
}

variable "azure_api_version" {
  description = "Azure OpenAI API version"
  type        = string
  default     = "2024-12-01-preview"
}

variable "llama_api_key" {
  description = "Llama API key for seeded Tesslate Apps that call LLMs directly"
  type        = string
  sensitive   = true
  default     = ""
}

# -----------------------------------------------------------------------------
# Redis / Azure Cache for Redis Configuration
# -----------------------------------------------------------------------------
variable "create_redis" {
  description = "Create an Azure Cache for Redis instance (false = use K8s-managed Redis)"
  type        = bool
  default     = false
}

variable "redis_sku" {
  description = "Azure Cache for Redis SKU (Basic / Standard / Premium)"
  type        = string
  default     = "Standard"
}

variable "redis_capacity" {
  description = "Azure Cache for Redis capacity (0=C0/250MB, 1=C1/1GB, ...)"
  type        = number
  default     = 0
}

# -----------------------------------------------------------------------------
# Team Access (AAD groups for AKS RBAC role bindings)
# -----------------------------------------------------------------------------
variable "aks_admin_group_object_ids" {
  description = "Azure AD group object IDs granted cluster-admin RBAC. Required."
  type        = list(string)

  validation {
    condition     = length(var.aks_admin_group_object_ids) > 0
    error_message = "At least one AAD group object ID is required to admin the AKS cluster."
  }
}

# -----------------------------------------------------------------------------
# Key Vault Access (for the tfvars-backup vault — see keyvault.tf)
# -----------------------------------------------------------------------------
variable "kv_secrets_officer_object_ids" {
  description = "AAD user/group object IDs granted Key Vault Secrets Officer on the per-env Key Vault. Use for engineers driving azure-secrets.sh."
  type        = list(string)
  default     = []
}

variable "aks_deployer_group_object_ids" {
  description = "Azure AD group object IDs granted deployer RBAC (deploy + read all)"
  type        = list(string)
  default     = []
}

variable "aks_observer_group_object_ids" {
  description = "Azure AD group object IDs granted observer RBAC (read-only + logs)"
  type        = list(string)
  default     = []
}

variable "aks_debugger_group_object_ids" {
  description = "Azure AD group object IDs granted debugger RBAC (deployer + exec)"
  type        = list(string)
  default     = []
}

# -----------------------------------------------------------------------------
# Replica & Scaling Configuration
# -----------------------------------------------------------------------------
variable "nginx_ingress_replicas" {
  description = "Number of NGINX ingress controller replicas"
  type        = number
  default     = 2
}

variable "coredns_replicas" {
  description = "Number of CoreDNS replicas"
  type        = number
  default     = 2
}
