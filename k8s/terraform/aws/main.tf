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
  }

  # Uncomment and configure for remote state storage
  # backend "s3" {
  #   bucket         = "tesslate-terraform-state"
  #   key            = "eks/terraform.tfstate"
  #   region         = "us-east-1"
  #   encrypt        = true
  #   dynamodb_table = "tesslate-terraform-locks"
  # }
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
# Kubernetes Provider (configured after EKS cluster creation)
# -----------------------------------------------------------------------------
provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  token                  = data.aws_eks_cluster_auth.cluster.token
}

# -----------------------------------------------------------------------------
# Helm Provider
# -----------------------------------------------------------------------------
provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
    token                  = data.aws_eks_cluster_auth.cluster.token
  }
}

# -----------------------------------------------------------------------------
# Kubectl Provider
# -----------------------------------------------------------------------------
provider "kubectl" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  token                  = data.aws_eks_cluster_auth.cluster.token
  load_config_file       = false
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

  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    Domain      = var.domain_name
  }

  # AZs to use (limit to 3 for cost optimization)
  azs = slice(data.aws_availability_zones.available.names, 0, 3)
}
