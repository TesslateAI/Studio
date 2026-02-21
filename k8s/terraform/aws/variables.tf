# =============================================================================
# Terraform Variables for Tesslate Studio AWS EKS
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
  description = "Environment name (e.g., production, staging)"
  type        = string
  default     = "production"
}

variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

# -----------------------------------------------------------------------------
# Image Configuration
# -----------------------------------------------------------------------------
variable "image_tag" {
  description = "Docker image tag for ECR images (defaults to environment name if empty)"
  type        = string
  default     = ""
}

# -----------------------------------------------------------------------------
# Domain Configuration
# -----------------------------------------------------------------------------
variable "domain_name" {
  description = "Primary domain name (e.g., your-domain.com)"
  type        = string
}

variable "wildcard_domain" {
  description = "Wildcard domain for user projects (e.g., *.your-domain.com)"
  type        = string
  default     = ""
}

# -----------------------------------------------------------------------------
# Cloudflare Configuration (for external-dns)
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
  description = "Cloudflare zone name (e.g., tesslate.com). Must match the actual Cloudflare zone, not a subdomain. Used by cert-manager for DNS01 challenge zone discovery."
  type        = string
  default     = ""
}

# -----------------------------------------------------------------------------
# VPC Configuration
# -----------------------------------------------------------------------------
variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "enable_nat_gateway" {
  description = "Enable NAT Gateway for private subnets"
  type        = bool
  default     = true
}

variable "single_nat_gateway" {
  description = "Use a single NAT Gateway (cost optimization for non-prod)"
  type        = bool
  default     = true
}

# -----------------------------------------------------------------------------
# EKS Configuration
# -----------------------------------------------------------------------------
variable "eks_cluster_version" {
  description = "Kubernetes version for EKS cluster"
  type        = string
  default     = "1.35"
}

variable "eks_node_instance_types" {
  description = "Instance types for EKS managed node group"
  type        = list(string)
  default     = ["t3.large"]
}

variable "eks_node_desired_size" {
  description = "Desired number of nodes in EKS node group"
  type        = number
  default     = 2
}

variable "eks_node_min_size" {
  description = "Minimum number of nodes in EKS node group"
  type        = number
  default     = 1
}

variable "eks_node_max_size" {
  description = "Maximum number of nodes in EKS node group"
  type        = number
  default     = 5
}

variable "eks_node_disk_size" {
  description = "Disk size in GB for EKS nodes"
  type        = number
  default     = 50
}

variable "eks_spot_desired_size" {
  description = "Desired number of spot nodes (set 0 to disable spot node group)"
  type        = number
  default     = 1
}

variable "eks_spot_max_size" {
  description = "Maximum number of spot nodes"
  type        = number
  default     = 10
}

# -----------------------------------------------------------------------------
# S3 Configuration
# -----------------------------------------------------------------------------
variable "s3_bucket_prefix" {
  description = "Prefix for S3 bucket name (will be appended with random suffix)"
  type        = string
  default     = "tesslate-projects"
}

variable "s3_force_destroy" {
  description = "Allow bucket to be destroyed even if not empty"
  type        = bool
  default     = false
}

# -----------------------------------------------------------------------------
# Database Configuration (RDS PostgreSQL)
# -----------------------------------------------------------------------------
variable "create_rds" {
  description = "Create RDS PostgreSQL instance (false = use K8s-managed postgres)"
  type        = bool
  default     = false
}

variable "rds_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t4g.small"
}

variable "rds_allocated_storage" {
  description = "RDS allocated storage in GB"
  type        = number
  default     = 20
}

variable "rds_database_name" {
  description = "RDS database name"
  type        = string
  default     = "tesslate"
}

variable "rds_username" {
  description = "RDS master username"
  type        = string
  default     = "tesslate_admin"
}

# -----------------------------------------------------------------------------
# Application Secrets (passed to K8s)
# -----------------------------------------------------------------------------
variable "postgres_password" {
  description = "PostgreSQL password"
  type        = string
  sensitive   = true
}

variable "app_secret_key" {
  description = "Application secret key for JWT signing"
  type        = string
  sensitive   = true
}

variable "litellm_api_base" {
  description = "DEPRECATED: LiteLLM is now self-hosted. This variable is kept for backward compatibility with existing tfvars and will be ignored."
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
  default     = "claude-sonnet-4.6"
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

# -----------------------------------------------------------------------------
# SMTP Configuration (Email / 2FA)
# -----------------------------------------------------------------------------
variable "smtp_host" {
  description = "SMTP server hostname"
  type        = string
  default     = ""
}

variable "smtp_port" {
  description = "SMTP server port"
  type        = number
  default     = 587
}

variable "smtp_username" {
  description = "SMTP authentication username"
  type        = string
  default     = ""
  sensitive   = true
}

variable "smtp_password" {
  description = "SMTP authentication password"
  type        = string
  default     = ""
  sensitive   = true
}

variable "smtp_use_tls" {
  description = "Whether to use TLS for SMTP"
  type        = bool
  default     = true
}

variable "smtp_sender_email" {
  description = "Email address to send from"
  type        = string
  default     = ""
}

variable "two_fa_enabled" {
  description = "Enable email 2FA for email/password logins"
  type        = bool
  default     = false
}

# -----------------------------------------------------------------------------
# Feature Flags
# -----------------------------------------------------------------------------
variable "enable_cluster_autoscaler" {
  description = "Enable Kubernetes Cluster Autoscaler"
  type        = bool
  default     = true
}

variable "enable_metrics_server" {
  description = "Enable Metrics Server for HPA"
  type        = bool
  default     = true
}

variable "enable_external_dns" {
  description = "Enable external-dns for automatic DNS management"
  type        = bool
  default     = true
}

variable "enable_cert_manager" {
  description = "Enable cert-manager for TLS certificates"
  type        = bool
  default     = true
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
# Advanced Settings
# -----------------------------------------------------------------------------
variable "eks_addon_versions" {
  description = "Override versions for EKS addons"
  type        = map(string)
  default     = {}
}

# -----------------------------------------------------------------------------
# LiteLLM Self-Hosted Deployment
# -----------------------------------------------------------------------------
variable "litellm_create_rds" {
  description = "Use RDS for LiteLLM database (false = K8s-managed PostgreSQL)"
  type        = bool
  default     = false
}

variable "litellm_rds_instance_class" {
  description = "RDS instance class for LiteLLM database (only when litellm_create_rds = true)"
  type        = string
  default     = "db.t4g.micro"
}

variable "litellm_rds_allocated_storage" {
  description = "RDS allocated storage in GB for LiteLLM (only when litellm_create_rds = true)"
  type        = number
  default     = 20
}

variable "litellm_db_password" {
  description = "PostgreSQL password for LiteLLM database"
  type        = string
  sensitive   = true
  default     = ""
}

variable "litellm_image_tag" {
  description = "LiteLLM Docker image tag (from ghcr.io/berriai/litellm). Pin to a specific version for production stability. Requires >= v1.75.8 for Bedrock API key auth (boto3 >= 1.39.0)."
  type        = string
  default     = "main-v1.81.9-stable"
}

variable "litellm_public_access" {
  description = "Expose LiteLLM publicly via ingress at litellm.{domain} (false = internal ClusterIP only)"
  type        = bool
  default     = false
}

variable "bedrock_api_key" {
  description = "AWS Bedrock API key (bearer token) for LiteLLM proxy. Requires boto3 >= 1.39.0 in the LiteLLM image."
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
  description = "GCP project ID for Vertex AI"
  type        = string
  default     = ""
}

variable "vertex_location" {
  description = "GCP region for Vertex AI (e.g., us-central1)"
  type        = string
  default     = "us-central1"
}

variable "vertex_credentials" {
  description = "GCP service account JSON (base64 encoded) for Vertex AI authentication"
  type        = string
  sensitive   = true
  default     = ""
}

variable "azure_api_key" {
  description = "Azure OpenAI API key"
  type        = string
  sensitive   = true
  default     = ""
}

variable "azure_api_base" {
  description = "Azure OpenAI endpoint URL (e.g., https://your-resource.openai.azure.com)"
  type        = string
  default     = ""
}

variable "azure_api_version" {
  description = "Azure OpenAI API version"
  type        = string
  default     = "2024-12-01-preview"
}

variable "additional_node_groups" {
  description = "Additional node groups for specific workloads"
  type = map(object({
    instance_types = list(string)
    desired_size   = number
    min_size       = number
    max_size       = number
    disk_size      = number
    labels         = map(string)
    taints = list(object({
      key    = string
      value  = string
      effect = string
    }))
  }))
  default = {}
}
