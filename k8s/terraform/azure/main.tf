# =============================================================================
# OpenSail - Azure AKS Terraform Configuration
# =============================================================================
# This Terraform configuration provisions the complete Azure infrastructure
# for running OpenSail on AKS with:
# - Resource Group (per-environment)
# - VNet with public/private subnets
# - AKS cluster with system + user node pools and Workload Identity
# - Azure Container Registry (ACR) for container images
# - Storage Account + Blob containers (projects / btrfs-snapshots / marketplace-bundles)
# - NGINX Ingress Controller for routing (Azure Standard Load Balancer)
# - cert-manager for TLS certificates (Cloudflare DNS01)
# - Cloudflare DNS records pointing at the ingress public IP
#
# Mirrors k8s/terraform/aws as closely as possible — same module pattern, same
# env names, same Cloudflare-fronted TLS. AWS-specific concepts that don't
# translate cleanly (Fargate, EKS access entries, IRSA) are replaced with
# their Azure equivalents (no equivalent / AKS RBAC / Workload Identity).
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.110"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 2.50"
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
    time = {
      source  = "hashicorp/time"
      version = "~> 0.12"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }

  # Backend configuration is provided via -backend-config flag at init time.
  # Production: terraform init -backend-config=backend-production.hcl
  # Beta:       terraform init -backend-config=backend-beta.hcl
  #
  # Backend uses Azure Storage Account (azurerm), not S3 — matches the cloud
  # we're deploying to so state never leaves the target cloud.
  backend "azurerm" {}
}

# -----------------------------------------------------------------------------
# Azure Providers
# -----------------------------------------------------------------------------
provider "azurerm" {
  features {
    resource_group {
      # Beta tfvars can flip this to true so terraform destroy works without
      # manually emptying every contained resource. Production stays false.
      prevent_deletion_if_contains_resources = true
    }
  }

  # By default the azurerm provider auto-registers every Resource Provider on
  # the subscription at startup (~80 parallel API calls). This swamps the WSL
  # DNS resolver and times out on machines with default resolv.conf. Caller is
  # expected to pre-register the small set we actually need:
  #
  #   az provider register --namespace Microsoft.ContainerService
  #   az provider register --namespace Microsoft.ContainerRegistry
  #   az provider register --namespace Microsoft.Network
  #   az provider register --namespace Microsoft.Storage
  #   az provider register --namespace Microsoft.DBforPostgreSQL
  #   az provider register --namespace Microsoft.Cache
  #   az provider register --namespace Microsoft.ManagedIdentity
  #
  # (azure-deploy.sh init runs these.)
  skip_provider_registration = true
}

provider "azuread" {}

# -----------------------------------------------------------------------------
# Data Sources
# -----------------------------------------------------------------------------
data "azurerm_client_config" "current" {}

data "azurerm_subscription" "current" {}

# -----------------------------------------------------------------------------
# Kubernetes / Helm / kubectl providers
# -----------------------------------------------------------------------------
# Reference the cluster resource attributes directly (NOT a data source). The
# kubernetes-family providers resolve unknown values lazily at apply time —
# they only need the values when an actual `kubernetes_*` / `helm_*` /
# `kubectl_*` resource is being created. Using a data source here forced a
# read-before-apply ordering that broke true one-pass deployments.
#
# Authenticates via the AKS-issued admin client cert in `kube_admin_config`.
# Beta has `local_account_disabled = false`, so this works. Production
# (`local_account_disabled = true`) would need exec-based AAD auth via
# kubelogin — out of scope for the beta-bootstrap path.
provider "kubernetes" {
  host                   = azurerm_kubernetes_cluster.this.kube_admin_config[0].host
  client_certificate     = base64decode(azurerm_kubernetes_cluster.this.kube_admin_config[0].client_certificate)
  client_key             = base64decode(azurerm_kubernetes_cluster.this.kube_admin_config[0].client_key)
  cluster_ca_certificate = base64decode(azurerm_kubernetes_cluster.this.kube_admin_config[0].cluster_ca_certificate)
}

provider "helm" {
  kubernetes {
    host                   = azurerm_kubernetes_cluster.this.kube_admin_config[0].host
    client_certificate     = base64decode(azurerm_kubernetes_cluster.this.kube_admin_config[0].client_certificate)
    client_key             = base64decode(azurerm_kubernetes_cluster.this.kube_admin_config[0].client_key)
    cluster_ca_certificate = base64decode(azurerm_kubernetes_cluster.this.kube_admin_config[0].cluster_ca_certificate)
  }
}

provider "kubectl" {
  host                   = azurerm_kubernetes_cluster.this.kube_admin_config[0].host
  client_certificate     = base64decode(azurerm_kubernetes_cluster.this.kube_admin_config[0].client_certificate)
  client_key             = base64decode(azurerm_kubernetes_cluster.this.kube_admin_config[0].client_key)
  cluster_ca_certificate = base64decode(azurerm_kubernetes_cluster.this.kube_admin_config[0].cluster_ca_certificate)
  load_config_file       = false
}

# -----------------------------------------------------------------------------
# Random suffix for globally-unique resource names
# Storage account names must be globally unique and 3–24 lowercase chars only.
# ACR names share the same constraint (5–50 lowercase alphanumerics).
# -----------------------------------------------------------------------------
resource "random_id" "suffix" {
  byte_length = 4
}

# -----------------------------------------------------------------------------
# Local Variables
# -----------------------------------------------------------------------------
locals {
  cluster_name        = "${var.project_name}-${var.environment}-aks"
  resource_group_name = "${var.project_name}-${var.environment}-rg"
  acr_name            = "${var.project_name}${var.environment}acr${random_id.suffix.hex}"

  # Image tag defaults to environment name (e.g., "beta", "production")
  image_tag = var.image_tag != "" ? var.image_tag : var.environment

  # Cloudflare zone name for cert-manager DNS01 challenges. See aws/main.tf
  # for the rule — same logic applies here.
  cloudflare_zone_name = var.cloudflare_zone_name != "" ? var.cloudflare_zone_name : var.domain_name

  dns_subdomain = (
    local.cloudflare_zone_name == var.domain_name
    ? "@"
    : trimsuffix(trimsuffix(var.domain_name, local.cloudflare_zone_name), ".")
  )

  acr_login_server = "${local.acr_name}.azurecr.io"

  # Per-image ACR repository URLs — referenced from kubernetes.tf to seed
  # APP_IMAGE_REGISTRY_PREFIX and tesslate-app-secrets.K8S_DEVSERVER_IMAGE
  # without depending on the kustomize overlay being applied.
  acr_backend_url     = "${local.acr_login_server}/${var.project_name}-backend"
  acr_frontend_url    = "${local.acr_login_server}/${var.project_name}-frontend"
  acr_devserver_url   = "${local.acr_login_server}/${var.project_name}-devserver"
  acr_ast_url         = "${local.acr_login_server}/${var.project_name}-ast"
  acr_marketplace_url = "${local.acr_login_server}/${var.project_name}-marketplace"
  acr_btrfs_csi_url   = "${local.acr_login_server}/${var.project_name}-btrfs-csi"

  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    Domain      = var.domain_name
    ManagedBy   = "terraform"
  }
}

# -----------------------------------------------------------------------------
# Resource Group — owns every Azure resource in this environment
# -----------------------------------------------------------------------------
resource "azurerm_resource_group" "this" {
  name     = local.resource_group_name
  location = var.azure_region

  tags = local.common_tags
}
