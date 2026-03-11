# =============================================================================
# Tesslate Studio - AWS EKS Terraform Configuration
# =============================================================================
# This Terraform configuration provisions the complete AWS infrastructure
# for running Tesslate Studio on EKS with:
# - VPC with public/private subnets
# - EKS cluster with managed node groups
# - S3 bucket for project hibernation
# - ECR repositories for container images
# - NGINX Ingress Controller for routing
# - cert-manager for TLS certificates
# - external-dns for Cloudflare DNS management
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.25"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.12"
    }
    kubectl = {
      source  = "gavinbunney/kubectl"
      version = "~> 1.14"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
  }

  # Backend configuration is provided via -backend-config flag at init time
  # Production: terraform init -backend-config=backend-production.hcl
  # Beta:       terraform init -backend-config=backend-beta.hcl
  backend "s3" {}
}

# -----------------------------------------------------------------------------
# AWS Provider
# -----------------------------------------------------------------------------
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "tesslate-studio"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# -----------------------------------------------------------------------------
# Data Sources
# -----------------------------------------------------------------------------
data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

# Get EKS cluster auth token after cluster is created
data "aws_eks_cluster_auth" "cluster" {
  name = module.eks.cluster_name

  depends_on = [module.eks]
}

# -----------------------------------------------------------------------------
# Kubernetes Provider (exec-based EKS auth via eks-deployer role)
# -----------------------------------------------------------------------------
provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--region", data.aws_region.current.name, "--role-arn", aws_iam_role.eks_deployer.arn]
  }
}

# -----------------------------------------------------------------------------
# Helm Provider (exec-based EKS auth via eks-deployer role)
# -----------------------------------------------------------------------------
provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)

    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--region", data.aws_region.current.name, "--role-arn", aws_iam_role.eks_deployer.arn]
    }
  }
}

# -----------------------------------------------------------------------------
# Kubectl Provider (exec-based EKS auth via eks-deployer role)
# -----------------------------------------------------------------------------
provider "kubectl" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  load_config_file       = false

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--region", data.aws_region.current.name, "--role-arn", aws_iam_role.eks_deployer.arn]
  }
}

# -----------------------------------------------------------------------------
# Random suffix for unique resource names
# -----------------------------------------------------------------------------
resource "random_id" "suffix" {
  byte_length = 4
}

# -----------------------------------------------------------------------------
# Local Variables
# -----------------------------------------------------------------------------
locals {
  cluster_name = "${var.project_name}-${var.environment}-eks"

  # Image tag defaults to environment name (e.g., "beta", "production")
  image_tag = var.image_tag != "" ? var.image_tag : var.environment

  # Cloudflare zone name for cert-manager DNS01 challenges
  # Defaults to domain_name (works when domain == zone, e.g., your-domain.com)
  # Must be explicitly set when domain is a subdomain (e.g., your-domain.com → tesslate.com)
  cloudflare_zone_name = var.cloudflare_zone_name != "" ? var.cloudflare_zone_name : var.domain_name

  # DNS subdomain relative to Cloudflare zone (e.g., "studio" for "your-domain.com" in zone "tesslate.com")
  # When domain == zone (e.g., your-domain.com), subdomain is "@" (zone apex)
  dns_subdomain = (
    local.cloudflare_zone_name == var.domain_name
    ? "@"
    : trimsuffix(trimsuffix(var.domain_name, local.cloudflare_zone_name), ".")
  )

  # Subnets for EKS node groups — filtered by eks_node_azs if set
  node_subnet_ids = (
    length(var.eks_node_azs) > 0
    ? [for i, az in local.azs : module.vpc.private_subnets[i] if contains(var.eks_node_azs, az)]
    : module.vpc.private_subnets
  )

  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    Domain      = var.domain_name
  }

  # AZs to use (limit to 3 for cost optimization)
  azs = slice(data.aws_availability_zones.available.names, 0, 3)
}
