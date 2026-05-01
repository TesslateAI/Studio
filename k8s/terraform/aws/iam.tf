# =============================================================================
# IAM Roles and Policies for OpenSail
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
    s3_policy             = aws_iam_policy.tesslate_s3_access.arn
    ecr_policy            = aws_iam_policy.tesslate_ecr_access.arn
    marketplace_s3_policy = aws_iam_policy.tesslate_marketplace_s3_access.arn
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

# Marketplace S3 access policy — read+write the bundle archives bucket.
# Used by the tesslate-marketplace pod (which reuses tesslate-backend-sa
# and therefore inherits this IRSA role). Scoped to the bundles bucket
# only — the project-hibernation bucket has its own statement above.
resource "aws_iam_policy" "tesslate_marketplace_s3_access" {
  name        = "${local.cluster_name}-tesslate-marketplace-s3-access"
  description = "Marketplace bundle archive read/write on the dedicated S3 bucket"

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
          "s3:GetBucketLocation",
        ]
        Resource = [
          aws_s3_bucket.tesslate_marketplace_bundles.arn,
          "${aws_s3_bucket.tesslate_marketplace_bundles.arn}/*",
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
# IRSA for btrfs CSI Driver (Snapshot Storage)
# -----------------------------------------------------------------------------
module "btrfs_csi_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.30"

  role_name = "${local.cluster_name}-btrfs-csi"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:tesslate-btrfs-csi-node"]
    }
  }

  role_policy_arns = {
    s3_policy = aws_iam_policy.btrfs_csi_s3_access.arn
  }

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# IRSA for Volume Hub (Manifest Storage)
# -----------------------------------------------------------------------------
module "volume_hub_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.30"

  role_name = "${local.cluster_name}-volume-hub"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:tesslate-volume-hub"]
    }
  }

  role_policy_arns = {
    s3_policy = aws_iam_policy.btrfs_csi_s3_access.arn
  }

  tags = local.common_tags
}

# S3 access policy for btrfs snapshot sync/restore
resource "aws_iam_policy" "btrfs_csi_s3_access" {
  name        = "${local.cluster_name}-btrfs-csi-s3-access"
  description = "Policy for btrfs CSI driver to sync/restore volume snapshots to S3"

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
          "s3:GetBucketLocation",
          "s3:ListMultipartUploadParts",
          "s3:AbortMultipartUpload"
        ]
        Resource = [
          aws_s3_bucket.btrfs_snapshots.arn,
          "${aws_s3_bucket.btrfs_snapshots.arn}/*"
        ]
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

# =============================================================================
# Team Access Roles -- scoped roles for team members per environment
# =============================================================================
# Four roles: observer, deployer, debugger, admin. Each maps to K8s groups
# via EKS access entries (no EKS policy_associations -- custom K8s RBAC).
# Deployer and debugger automatically include observer read permissions via
# multi-group mapping in eks.tf access_entries.
#
# Trust policy: account root. Access is controlled by attaching the
# corresponding "assume" managed policy to IAM users -- no Terraform needed
# to onboard/offboard team members.
#
# Onboarding:
#   1. aws iam create-user --user-name tesslate-alice --path /team/
#   2. aws iam create-access-key --user-name tesslate-alice
#   3. aws iam add-user-to-group --user-name tesslate-alice \
#        --group-name tesslate-{env}-deployers
# =============================================================================

# -----------------------------------------------------------------------------
# Team Deployer -- deploy platform + read all
# -----------------------------------------------------------------------------
resource "aws_iam_role" "team_deployer" {
  name = "${local.cluster_name}-team-deployer"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${local.cluster_name}-team-deployer"
  })
}

resource "aws_iam_policy" "team_deployer" {
  name        = "${local.cluster_name}-team-deployer"
  description = "Team deployer: EKS describe + ECR push/pull/browse + CloudWatch Logs read"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EKSDescribe"
        Effect   = "Allow"
        Action   = ["eks:DescribeCluster"]
        Resource = local.cluster_arn
      },
      {
        Sid      = "EKSList"
        Effect   = "Allow"
        Action   = ["eks:ListClusters"]
        Resource = "*"
      },
      {
        Sid    = "ECRDiscover"
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:DescribeRepositories",
        ]
        Resource = "*"
      },
      {
        Sid    = "ECRPushPull"
        Effect = "Allow"
        Action = [
          "ecr:ListImages",
          "ecr:DescribeImages",
          "ecr:BatchCheckLayerAvailability",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
        ]
        Resource = "arn:aws:ecr:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:repository/tesslate-*"
      },
      {
        Sid      = "CloudWatchLogsDiscover"
        Effect   = "Allow"
        Action   = ["logs:DescribeLogGroups"]
        Resource = "*"
      },
      {
        Sid    = "CloudWatchLogsRead"
        Effect = "Allow"
        Action = [
          "logs:GetLogEvents",
          "logs:DescribeLogStreams",
          "logs:FilterLogEvents",
        ]
        Resource = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/eks/${local.cluster_name}/*"
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "team_deployer" {
  role       = aws_iam_role.team_deployer.name
  policy_arn = aws_iam_policy.team_deployer.arn
}

# Managed policy: attach to IAM users to grant deployer access
resource "aws_iam_policy" "assume_team_deployer" {
  name        = "${local.cluster_name}-assume-team-deployer"
  description = "Allows assuming the team deployer role for ${local.cluster_name}"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "sts:AssumeRole"
        Resource = aws_iam_role.team_deployer.arn
      }
    ]
  })

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# Team Observer -- read-only + CloudWatch Logs
# -----------------------------------------------------------------------------
resource "aws_iam_role" "team_observer" {
  name = "${local.cluster_name}-team-observer"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${local.cluster_name}-team-observer"
  })
}

resource "aws_iam_policy" "team_observer" {
  name        = "${local.cluster_name}-team-observer"
  description = "Team observer: EKS describe + ECR browse + CloudWatch Logs read"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EKSDescribe"
        Effect   = "Allow"
        Action   = ["eks:DescribeCluster"]
        Resource = local.cluster_arn
      },
      {
        Sid      = "EKSList"
        Effect   = "Allow"
        Action   = ["eks:ListClusters"]
        Resource = "*"
      },
      {
        Sid    = "ECRDiscover"
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:DescribeRepositories",
        ]
        Resource = "*"
      },
      {
        Sid    = "ECRRead"
        Effect = "Allow"
        Action = [
          "ecr:ListImages",
          "ecr:DescribeImages",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
        ]
        Resource = "arn:aws:ecr:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:repository/tesslate-*"
      },
      {
        Sid      = "CloudWatchLogsDiscover"
        Effect   = "Allow"
        Action   = ["logs:DescribeLogGroups"]
        Resource = "*"
      },
      {
        Sid    = "CloudWatchLogsRead"
        Effect = "Allow"
        Action = [
          "logs:GetLogEvents",
          "logs:DescribeLogStreams",
          "logs:FilterLogEvents",
        ]
        Resource = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/eks/${local.cluster_name}/*"
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "team_observer" {
  role       = aws_iam_role.team_observer.name
  policy_arn = aws_iam_policy.team_observer.arn
}

# Managed policy: attach to IAM users to grant observer access
resource "aws_iam_policy" "assume_team_observer" {
  name        = "${local.cluster_name}-assume-team-observer"
  description = "Allows assuming the team observer role for ${local.cluster_name}"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "sts:AssumeRole"
        Resource = aws_iam_role.team_observer.arn
      }
    ]
  })

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# Team Debugger -- deployer + kubectl exec (highest non-admin tier)
# -----------------------------------------------------------------------------
resource "aws_iam_role" "team_debugger" {
  name = "${local.cluster_name}-team-debugger"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${local.cluster_name}-team-debugger"
  })
}

resource "aws_iam_policy" "team_debugger" {
  name        = "${local.cluster_name}-team-debugger"
  description = "Team debugger: EKS describe + ECR push/pull/browse + CloudWatch Logs read"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EKSDescribe"
        Effect   = "Allow"
        Action   = ["eks:DescribeCluster"]
        Resource = local.cluster_arn
      },
      {
        Sid      = "EKSList"
        Effect   = "Allow"
        Action   = ["eks:ListClusters"]
        Resource = "*"
      },
      {
        Sid    = "ECRDiscover"
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:DescribeRepositories",
        ]
        Resource = "*"
      },
      {
        Sid    = "ECRPushPull"
        Effect = "Allow"
        Action = [
          "ecr:ListImages",
          "ecr:DescribeImages",
          "ecr:BatchCheckLayerAvailability",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
        ]
        Resource = "arn:aws:ecr:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:repository/tesslate-*"
      },
      {
        Sid      = "CloudWatchLogsDiscover"
        Effect   = "Allow"
        Action   = ["logs:DescribeLogGroups"]
        Resource = "*"
      },
      {
        Sid    = "CloudWatchLogsRead"
        Effect = "Allow"
        Action = [
          "logs:GetLogEvents",
          "logs:DescribeLogStreams",
          "logs:FilterLogEvents",
        ]
        Resource = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/eks/${local.cluster_name}/*"
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "team_debugger" {
  role       = aws_iam_role.team_debugger.name
  policy_arn = aws_iam_policy.team_debugger.arn
}

# Managed policy: attach to IAM users to grant debugger access
resource "aws_iam_policy" "assume_team_debugger" {
  name        = "${local.cluster_name}-assume-team-debugger"
  description = "Allows assuming the team debugger role for ${local.cluster_name}"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "sts:AssumeRole"
        Resource = aws_iam_role.team_debugger.arn
      }
    ]
  })

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# Team Admin -- full cluster admin (debugger + secrets, RBAC, namespace mgmt)
# -----------------------------------------------------------------------------
# Hierarchy: observer < deployer < debugger < admin
# Uses EKS AmazonEKSClusterAdminPolicy (same as eks_deployer) instead of
# kubernetes_groups, so it gets full cluster admin without custom RBAC.
# The existing eks_deployer role + eks_admin_iam_arns trust policy is kept
# for backwards compatibility -- remove after verifying policy-attached model.
# -----------------------------------------------------------------------------
resource "aws_iam_role" "team_admin" {
  name = "${local.cluster_name}-team-admin"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${local.cluster_name}-team-admin"
  })
}

resource "aws_iam_policy" "team_admin" {
  name        = "${local.cluster_name}-team-admin"
  description = "Team admin: full platform admin (EKS, ECR, S3, SecretsManager, IAM team mgmt, CloudWatch)"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # EKS — full access to this cluster
      {
        Sid    = "EKSFull"
        Effect = "Allow"
        Action = [
          "eks:DescribeCluster",
          "eks:ListClusters",
          "eks:ListNodegroups",
          "eks:DescribeNodegroup",
          "eks:ListAddons",
          "eks:DescribeAddon",
          "eks:ListUpdates",
          "eks:DescribeUpdate",
          "eks:AccessKubernetesApi",
        ]
        Resource = "*"
      },
      # ECR — full management of tesslate repos
      {
        Sid    = "ECRDiscover"
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:DescribeRepositories",
        ]
        Resource = "*"
      },
      {
        Sid    = "ECRFull"
        Effect = "Allow"
        Action = [
          "ecr:ListImages",
          "ecr:DescribeImages",
          "ecr:BatchCheckLayerAvailability",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchDeleteImage",
          "ecr:PutLifecyclePolicy",
          "ecr:GetLifecyclePolicy",
          "ecr:ListTagsForResource",
          "ecr:TagResource",
        ]
        Resource = "arn:aws:ecr:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:repository/tesslate-*"
      },
      # S3 — terraform state access
      {
        Sid    = "TerraformState"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:DeleteObject",
        ]
        Resource = [
          "arn:aws:s3:::<TERRAFORM_STATE_BUCKET>",
          "arn:aws:s3:::<TERRAFORM_STATE_BUCKET>/*",
        ]
      },
      {
        Sid      = "S3List"
        Effect   = "Allow"
        Action   = ["s3:ListAllMyBuckets"]
        Resource = "*"
      },
      # DynamoDB — terraform locks
      {
        Sid    = "TerraformLocks"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem",
          "dynamodb:DescribeTable",
        ]
        Resource = "arn:aws:dynamodb:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/<AWS_IAM_USER>-locks"
      },
      # SecretsManager — full access for admin (create, read, update, delete)
      {
        Sid    = "SecretsFull"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret",
          "secretsmanager:CreateSecret",
          "secretsmanager:UpdateSecret",
          "secretsmanager:PutSecretValue",
          "secretsmanager:DeleteSecret",
          "secretsmanager:TagResource",
        ]
        Resource = "arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:tesslate/*"
      },
      {
        Sid      = "SecretsList"
        Effect   = "Allow"
        Action   = ["secretsmanager:ListSecrets"]
        Resource = "*"
      },
      # IAM — team user management (create users, manage group membership)
      {
        Sid    = "IAMTeamManage"
        Effect = "Allow"
        Action = [
          "iam:CreateUser",
          "iam:DeleteUser",
          "iam:GetUser",
          "iam:ListUsers",
          "iam:TagUser",
          "iam:CreateAccessKey",
          "iam:DeleteAccessKey",
          "iam:ListAccessKeys",
          "iam:AddUserToGroup",
          "iam:RemoveUserFromGroup",
          "iam:ListGroupsForUser",
        ]
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/team/*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:group/team/*",
        ]
      },
      {
        Sid    = "IAMListGroups"
        Effect = "Allow"
        Action = [
          "iam:ListGroups",
          "iam:GetGroup",
        ]
        Resource = "*"
      },
      # EC2 — read-only for infrastructure visibility
      {
        Sid    = "EC2Read"
        Effect = "Allow"
        Action = [
          "ec2:DescribeInstances",
          "ec2:DescribeVolumes",
          "ec2:DescribeSnapshots",
          "ec2:DescribeVpcs",
          "ec2:DescribeSubnets",
          "ec2:DescribeSecurityGroups",
        ]
        Resource = "*"
      },
      # CloudWatch Logs — full read
      {
        Sid      = "CloudWatchLogsDiscover"
        Effect   = "Allow"
        Action   = ["logs:DescribeLogGroups"]
        Resource = "*"
      },
      {
        Sid    = "CloudWatchLogsRead"
        Effect = "Allow"
        Action = [
          "logs:GetLogEvents",
          "logs:DescribeLogStreams",
          "logs:FilterLogEvents",
          "logs:GetLogRecord",
          "logs:GetQueryResults",
          "logs:StartQuery",
          "logs:StopQuery",
        ]
        Resource = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/eks/${local.cluster_name}/*"
      },
      # STS — caller identity (needed for aws sts get-caller-identity)
      {
        Sid      = "STSIdentity"
        Effect   = "Allow"
        Action   = ["sts:GetCallerIdentity"]
        Resource = "*"
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "team_admin" {
  role       = aws_iam_role.team_admin.name
  policy_arn = aws_iam_policy.team_admin.arn
}

# Managed policy: attach to IAM users to grant admin access
resource "aws_iam_policy" "assume_team_admin" {
  name        = "${local.cluster_name}-assume-team-admin"
  description = "Allows assuming the team admin role for ${local.cluster_name}"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "sts:AssumeRole"
        Resource = aws_iam_role.team_admin.arn
      }
    ]
  })

  tags = local.common_tags
}

# =============================================================================
# Team Access Groups -- add users to groups instead of attaching policies directly
# =============================================================================
# Onboarding workflow:
#   aws iam add-user-to-group --user-name alice \
#     --group-name tesslate-production-deployers
#
# Hierarchy is built into the roles (observer < deployer < debugger < admin),
# so a user only needs one group membership per environment.
# =============================================================================

resource "aws_iam_group" "team_observers" {
  name = "${var.project_name}-${var.environment}-observers"
  path = "/team/"
}

resource "aws_iam_group_policy_attachment" "team_observers" {
  group      = aws_iam_group.team_observers.name
  policy_arn = aws_iam_policy.assume_team_observer.arn
}

resource "aws_iam_group" "team_deployers" {
  name = "${var.project_name}-${var.environment}-deployers"
  path = "/team/"
}

resource "aws_iam_group_policy_attachment" "team_deployers" {
  group      = aws_iam_group.team_deployers.name
  policy_arn = aws_iam_policy.assume_team_deployer.arn
}

resource "aws_iam_group" "team_debuggers" {
  name = "${var.project_name}-${var.environment}-debuggers"
  path = "/team/"
}

resource "aws_iam_group_policy_attachment" "team_debuggers" {
  group      = aws_iam_group.team_debuggers.name
  policy_arn = aws_iam_policy.assume_team_debugger.arn
}

resource "aws_iam_group" "team_admins" {
  name = "${var.project_name}-${var.environment}-admins"
  path = "/team/"
}

resource "aws_iam_group_policy_attachment" "team_admins" {
  group      = aws_iam_group.team_admins.name
  policy_arn = aws_iam_policy.assume_team_admin.arn
}

# =============================================================================
# GitHub Actions CI/CD IAM User
# =============================================================================
# Creates an IAM user with access keys for GitHub Actions deploy workflows.
# Gated on var.create_github_actions_user. After terraform apply, retrieve
# credentials via:
#   terraform output github_actions_access_key_id
#   terraform output -raw github_actions_secret_access_key
# Then add them as GitHub repo secrets: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
# =============================================================================

resource "aws_iam_user" "github_actions" {
  count = var.create_github_actions_user ? 1 : 0

  name = "${var.project_name}-${var.environment}-github-actions"
  path = "/ci/"

  tags = merge(local.common_tags, {
    Name = "${var.project_name}-${var.environment}-github-actions"
  })
}

resource "aws_iam_access_key" "github_actions" {
  count = var.create_github_actions_user ? 1 : 0

  user = aws_iam_user.github_actions[0].name
}

resource "aws_iam_policy" "github_actions" {
  count = var.create_github_actions_user ? 1 : 0

  name        = "${var.project_name}-${var.environment}-github-actions"
  description = "Policy for GitHub Actions CI/CD deploy workflows"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # ECR — push/pull images
      {
        Sid    = "ECR"
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:DescribeRepositories",
          "ecr:ListImages",
        ]
        Resource = "*"
      },
      # EKS — update kubeconfig
      {
        Sid    = "EKS"
        Effect = "Allow"
        Action = [
          "eks:DescribeCluster",
          "eks:ListClusters",
        ]
        Resource = "*"
      },
      # Secrets Manager — download tfvars
      {
        Sid    = "SecretsManager"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
        ]
        Resource = "arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:tesslate/terraform/*"
      },
      # S3 — terraform state
      {
        Sid    = "TerraformState"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
        ]
        Resource = [
          "arn:aws:s3:::<TERRAFORM_STATE_BUCKET>",
          "arn:aws:s3:::<TERRAFORM_STATE_BUCKET>/*",
        ]
      },
      # DynamoDB — terraform locks
      {
        Sid    = "TerraformLocks"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem",
        ]
        Resource = "arn:aws:dynamodb:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/<AWS_IAM_USER>-locks"
      },
      # Infrastructure management — services terraform creates/manages
      {
        Sid    = "InfraManagement"
        Effect = "Allow"
        Action = [
          "ec2:*",
          "eks:*",
          "iam:*",
          "s3:*",
          "dynamodb:*",
          "ecr:*",
          "rds:*",
          "elasticloadbalancing:*",
          "autoscaling:*",
          "logs:*",
          "kms:*",
          "ssm:GetParameter",
        ]
        Resource = "*"
      },
      # STS — caller identity and assume role
      {
        Sid    = "STS"
        Effect = "Allow"
        Action = [
          "sts:GetCallerIdentity",
          "sts:AssumeRole",
        ]
        Resource = "*"
      },
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${var.project_name}-${var.environment}-github-actions"
  })
}

resource "aws_iam_user_policy_attachment" "github_actions" {
  count = var.create_github_actions_user ? 1 : 0

  user       = aws_iam_user.github_actions[0].name
  policy_arn = aws_iam_policy.github_actions[0].arn
}
