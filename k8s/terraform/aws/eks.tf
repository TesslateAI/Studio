# =============================================================================
# EKS Cluster Configuration for Tesslate Studio
# =============================================================================
# Creates an EKS cluster with managed node groups, EBS CSI driver,
# and required OIDC provider for IRSA (IAM Roles for Service Accounts).
# =============================================================================

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = local.cluster_name
  cluster_version = var.eks_cluster_version

  # Network configuration
  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # Cluster endpoint access
  cluster_endpoint_public_access  = true
  cluster_endpoint_private_access = true

  # Enable OIDC provider for IRSA
  enable_irsa = true

  # Cluster addons
  cluster_addons = {
    coredns = {
      most_recent = true
      configuration_values = jsonencode({
        computeType = "Fargate"
        # Reduce replicas for cost optimization
        replicaCount = 2
      })
    }
    kube-proxy = {
      most_recent = true
    }
    vpc-cni = {
      most_recent              = true
      before_compute           = true
      service_account_role_arn = module.vpc_cni_irsa.iam_role_arn
      configuration_values = jsonencode({
        env = {
          ENABLE_PREFIX_DELEGATION = "true"
          WARM_PREFIX_TARGET       = "1"
        }
      })
    }
    aws-ebs-csi-driver = {
      most_recent              = true
      service_account_role_arn = module.ebs_csi_irsa.iam_role_arn
    }
  }

  # EKS Managed Node Group
  eks_managed_node_groups = {
    # Primary node group for Tesslate workloads
    primary = {
      name            = "tess-primary"
      use_name_prefix = false

      instance_types = var.eks_node_instance_types
      capacity_type  = "ON_DEMAND"

      min_size     = var.eks_node_min_size
      max_size     = var.eks_node_max_size
      desired_size = var.eks_node_desired_size

      disk_size = var.eks_node_disk_size

      # Use latest Amazon Linux 2023 AMI
      ami_type = "AL2023_x86_64_STANDARD"

      # Shorter IAM role name
      iam_role_name            = "tess-primary-node"
      iam_role_use_name_prefix = false

      labels = {
        role        = "primary"
        environment = var.environment
      }

      tags = {
        "k8s.io/cluster-autoscaler/enabled"             = "true"
        "k8s.io/cluster-autoscaler/${local.cluster_name}" = "owned"
      }
    }

    # Optional: Spot instance node group for dev containers (cost savings)
    spot = {
      name            = "tess-spot"
      use_name_prefix = false

      instance_types = ["t3.large", "t3.xlarge", "t3a.large", "t3a.xlarge"]
      capacity_type  = "SPOT"

      min_size     = 0
      max_size     = 10
      desired_size = 1

      disk_size = var.eks_node_disk_size

      ami_type = "AL2023_x86_64_STANDARD"

      # Shorter IAM role name
      iam_role_name            = "tess-spot-node"
      iam_role_use_name_prefix = false

      labels = {
        role        = "spot"
        environment = var.environment
        "tesslate.io/workload-type" = "user-project"
      }

      taints = [
        {
          key    = "tesslate.io/spot"
          value  = "true"
          effect = "PREFER_NO_SCHEDULE"
        }
      ]

      tags = {
        "k8s.io/cluster-autoscaler/enabled"             = "true"
        "k8s.io/cluster-autoscaler/${local.cluster_name}" = "owned"
      }
    }
  }

  # Allow cluster admin access
  enable_cluster_creator_admin_permissions = true

  # Node security group additional rules
  # Note: EKS module v20+ includes some rules but we need explicit pod-to-pod
  # traffic across nodes for network policies to work correctly.
  node_security_group_additional_rules = {
    # Allow all ingress from within VPC for pod-to-pod communication across nodes
    # This is required for cross-node pod communication when using network policies
    ingress_vpc_all = {
      type        = "ingress"
      protocol    = "-1"
      from_port   = 0
      to_port     = 0
      cidr_blocks = [var.vpc_cidr]
      description = "Allow all ingress from VPC CIDR for pod-to-pod traffic"
    }
    # Allow all egress
    egress_all = {
      type        = "egress"
      protocol    = "-1"
      from_port   = 0
      to_port     = 0
      cidr_blocks = ["0.0.0.0/0"]
      description = "Allow all egress"
    }
  }

  tags = local.common_tags
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
# gp3 Storage Class (default for Tesslate)
# -----------------------------------------------------------------------------
resource "kubernetes_storage_class" "gp3" {
  metadata {
    name = "tesslate-block-storage"
    annotations = {
      "storageclass.kubernetes.io/is-default-class" = "false"
    }
    labels = {
      "app.kubernetes.io/name"    = "tesslate"
      "app.kubernetes.io/part-of" = "tesslate-studio"
    }
  }

  storage_provisioner    = "ebs.csi.aws.com"
  reclaim_policy         = "Delete"
  volume_binding_mode    = "WaitForFirstConsumer"
  allow_volume_expansion = true

  parameters = {
    type      = "gp3"
    fsType    = "ext4"
    encrypted = "true"
  }

  depends_on = [module.eks]
}
