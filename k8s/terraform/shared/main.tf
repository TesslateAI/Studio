# =============================================================================
# Tesslate Studio - Shared Infrastructure
# =============================================================================
# Manages resources shared across all environments:
# - ECR repositories (backend, frontend, devserver)
# - Platform EKS cluster for internal tools (Headscale VPN, etc.)
# - NGINX Ingress + cert-manager for platform routing/TLS
#
# Both production and beta push different image tags to the SAME ECR repos.
# The platform cluster is fully isolated (separate VPC) from production/beta.
#
# Adding a new platform tool = one new .tf file (e.g., grafana.tf, prometheus.tf).
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
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
  }

  # Backend configuration is provided via -backend-config flag at init time
  # Usage: terraform init -backend-config=backend.hcl
  backend "s3" {}
}

# -----------------------------------------------------------------------------
# AWS Provider
# -----------------------------------------------------------------------------
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "terraform"
      Stack     = "shared"
    }
  }
}

# -----------------------------------------------------------------------------
# Data Sources
# -----------------------------------------------------------------------------
data "aws_caller_identity" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_region" "current" {}

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
# Cloudflare Provider
# -----------------------------------------------------------------------------
provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# -----------------------------------------------------------------------------
# Local Variables
# -----------------------------------------------------------------------------
locals {
  cluster_name = "${var.project_name}-platform-eks"

  azs = slice(data.aws_availability_zones.available.names, 0, 3)

  common_tags = {
    Project = var.project_name
    Stack   = "shared"
  }
}
