# =============================================================================
# IAM Roles for Platform Cluster
# =============================================================================
# IRSA (IAM Roles for Service Accounts) for EKS addons and Helm charts.
# Minimal set — no app-specific roles needed for internal tools.
# =============================================================================

# =============================================================================
# EKS Deployer Role — role-based cluster access
# =============================================================================
# Scoped role for EKS operations. Users in var.eks_admin_iam_arns can assume
# this role to get cluster access via EKS access entries.
#
# Migration path:
#   1. Apply with <AWS_IAM_USER> (has direct access entry) to create role
#   2. Future: switch providers to assume_role, remove direct user entries
# =============================================================================

resource "aws_iam_role" "eks_deployer" {
  name = "${local.cluster_name}-eks-deployer"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = var.eks_admin_iam_arns
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${local.cluster_name}-eks-deployer"
  })
}

# -----------------------------------------------------------------------------
# IRSA for VPC CNI
# -----------------------------------------------------------------------------
module "vpc_cni_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.30"

  role_name             = "${local.cluster_name}-vpc-cni"
  attach_vpc_cni_policy = true
  vpc_cni_enable_ipv4   = true

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:aws-node"]
    }
  }

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# IRSA for EBS CSI Driver
# -----------------------------------------------------------------------------
module "ebs_csi_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.30"

  role_name             = "${local.cluster_name}-ebs-csi"
  attach_ebs_csi_policy = true

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:ebs-csi-controller-sa"]
    }
  }

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# IRSA for cert-manager (Cloudflare DNS01 — no AWS-specific permissions needed)
# -----------------------------------------------------------------------------
module "cert_manager_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.30"

  role_name = "${local.cluster_name}-cert-manager"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["cert-manager:cert-manager"]
    }
  }

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# IRSA for Headscale (S3 access for Litestream SQLite replication)
# -----------------------------------------------------------------------------
module "headscale_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.30"

  role_name = "${local.cluster_name}-headscale"

  role_policy_arns = {
    litestream = aws_iam_policy.headscale_litestream.arn
  }

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["headscale:headscale"]
    }
  }

  tags = local.common_tags
}

resource "aws_iam_policy" "headscale_litestream" {
  name        = "${local.cluster_name}-headscale-litestream"
  description = "Allow Headscale Litestream sidecar to replicate SQLite to S3"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
        ]
        Resource = [
          aws_s3_bucket.litestream.arn,
          "${aws_s3_bucket.litestream.arn}/*",
        ]
      }
    ]
  })
}
