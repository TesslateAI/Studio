# =============================================================================
# IAM Roles and Policies for Tesslate Studio
# =============================================================================
# Creates IRSA (IAM Roles for Service Accounts) for:
# - Tesslate backend (S3 access for hibernation)
# - external-dns (Route53/Cloudflare DNS management)
# - cert-manager (ACM certificate management)
# - cluster-autoscaler (node scaling)
# =============================================================================

# -----------------------------------------------------------------------------
# IRSA for Tesslate Backend (S3 Access)
# -----------------------------------------------------------------------------
module "tesslate_backend_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.30"

  role_name = "${local.cluster_name}-tesslate-backend"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["tesslate:tesslate-backend-sa"]
    }
  }

  role_policy_arns = {
    s3_policy = aws_iam_policy.tesslate_s3_access.arn
    ecr_policy = aws_iam_policy.tesslate_ecr_access.arn
  }

  tags = local.common_tags
}

# S3 access policy for project hibernation
resource "aws_iam_policy" "tesslate_s3_access" {
  name        = "${local.cluster_name}-tesslate-s3-access"
  description = "Policy for Tesslate backend to access S3 for project hibernation"

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
          "s3:GetBucketLocation"
        ]
        Resource = [
          aws_s3_bucket.tesslate_projects.arn,
          "${aws_s3_bucket.tesslate_projects.arn}/*"
        ]
      }
    ]
  })

  tags = local.common_tags
}

# ECR access policy for pulling devserver images
resource "aws_iam_policy" "tesslate_ecr_access" {
  name        = "${local.cluster_name}-tesslate-ecr-access"
  description = "Policy for Tesslate backend to pull ECR images"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage"
        ]
        Resource = "*"
      }
    ]
  })

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# IRSA for External DNS
# -----------------------------------------------------------------------------
module "external_dns_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.30"

  role_name = "${local.cluster_name}-external-dns"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["external-dns:external-dns"]
    }
  }

  # Note: For Cloudflare, we don't need Route53 permissions
  # The external-dns pod will use Cloudflare API token from secret
  # This role is mainly for AWS Secrets Manager access if needed

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# IRSA for cert-manager
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

  # For DNS-01 challenge with Cloudflare, no AWS permissions needed
  # cert-manager will use Cloudflare API token from secret

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# IRSA for Cluster Autoscaler
# -----------------------------------------------------------------------------
module "cluster_autoscaler_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.30"

  role_name                        = "${local.cluster_name}-cluster-autoscaler"
  attach_cluster_autoscaler_policy = true
  cluster_autoscaler_cluster_names = [local.cluster_name]

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      # Helm chart creates SA named: {release-name}-aws-cluster-autoscaler
      namespace_service_accounts = ["kube-system:cluster-autoscaler-aws-cluster-autoscaler"]
    }
  }

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# IRSA for AWS Load Balancer Controller (if using ALB instead of NGINX)
# -----------------------------------------------------------------------------
module "lb_controller_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.30"

  role_name                              = "${local.cluster_name}-lb-controller"
  attach_load_balancer_controller_policy = true

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:aws-load-balancer-controller"]
    }
  }

  tags = local.common_tags
}
