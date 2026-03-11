# =============================================================================
# Variables for Shared Infrastructure
# =============================================================================

# -----------------------------------------------------------------------------
# General Settings
# -----------------------------------------------------------------------------
variable "project_name" {
  description = "Name of the project (used for resource naming)"
  type        = string
  default     = "tesslate"
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

# -----------------------------------------------------------------------------
# VPC Configuration
# -----------------------------------------------------------------------------
variable "vpc_cidr" {
  description = "CIDR block for the platform VPC"
  type        = string
  default     = "10.1.0.0/16"
}

# -----------------------------------------------------------------------------
# Domain Configuration
# -----------------------------------------------------------------------------
variable "domain_name" {
  description = "Base domain name (e.g., tesslate.com)"
  type        = string
  default     = "tesslate.com"
}

# -----------------------------------------------------------------------------
# Cloudflare Configuration
# -----------------------------------------------------------------------------
variable "cloudflare_api_token" {
  description = "Cloudflare API token for DNS management"
  type        = string
  sensitive   = true
}

variable "cloudflare_zone_id" {
  description = "Cloudflare Zone ID for the domain"
  type        = string
}

variable "cloudflare_zone_name" {
  description = "Cloudflare zone name (must match actual Cloudflare zone)"
  type        = string
  default     = "tesslate.com"
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
  default     = ["t3.medium"]
}

variable "eks_node_desired_size" {
  description = "Desired number of nodes in EKS node group"
  type        = number
  default     = 1
}

variable "eks_node_min_size" {
  description = "Minimum number of nodes in EKS node group"
  type        = number
  default     = 1
}

variable "eks_node_max_size" {
  description = "Maximum number of nodes in EKS node group"
  type        = number
  default     = 2
}

variable "eks_node_disk_size" {
  description = "Disk size in GB for EKS nodes"
  type        = number
  default     = 30
}

# -----------------------------------------------------------------------------
# EKS Access Control
# -----------------------------------------------------------------------------
variable "eks_admin_iam_arns" {
  description = "IAM user/role ARNs allowed to assume the EKS deployer role for cluster access"
  type        = list(string)
  default     = []

  validation {
    condition     = length(var.eks_admin_iam_arns) > 0
    error_message = "eks_admin_iam_arns must contain at least one IAM ARN. The eks-deployer role trust policy cannot be empty."
  }
}

# -----------------------------------------------------------------------------
# Headscale Configuration
# -----------------------------------------------------------------------------
variable "headscale_subdomain" {
  description = "Subdomain for Headscale (e.g., 'headscale' -> headscale.tesslate.com)"
  type        = string
  default     = "headscale"
}

variable "headscale_image_tag" {
  description = "Headscale container image tag (e.g., '0.28.0')"
  type        = string
  default     = "0.28.0"
}

variable "headscale_base_domain" {
  description = "MagicDNS base domain for the Headscale mesh network (e.g., 'vpn.tesslate.com'). Must differ from the control server domain."
  type        = string
  default     = "vpn.tesslate.com"
}
