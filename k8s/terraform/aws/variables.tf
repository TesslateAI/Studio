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
# Domain Configuration
# -----------------------------------------------------------------------------
variable "domain_name" {
  description = "Primary domain name (e.g., saipriya.org)"
  type        = string
}

variable "wildcard_domain" {
  description = "Wildcard domain for user projects (e.g., *.saipriya.org)"
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
  default     = "1.29"
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
  default     = "db.t3.small"
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
  description = "LiteLLM API base URL"
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
  default     = "gpt-4o-mini"
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
# Advanced Settings
# -----------------------------------------------------------------------------
variable "eks_addon_versions" {
  description = "Override versions for EKS addons"
  type        = map(string)
  default     = {}
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
