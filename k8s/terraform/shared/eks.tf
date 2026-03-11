# =============================================================================
# EKS Cluster Configuration for Tesslate Platform
# =============================================================================
# A single ON_DEMAND node group for running internal tools (Headscale, etc.).
# No spot nodes, no snapshot controller, no cluster autoscaler.
# =============================================================================

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = local.cluster_name
  cluster_version = var.eks_cluster_version

  # Network
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
        replicaCount = 1
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

  # Single ON_DEMAND node group for platform workloads
  eks_managed_node_groups = {
    platform = {
      name            = "tess-platform"
      use_name_prefix = false

      instance_types = var.eks_node_instance_types
      capacity_type  = "ON_DEMAND"

      min_size     = var.eks_node_min_size
      max_size     = var.eks_node_max_size
      desired_size = var.eks_node_desired_size

      disk_size = var.eks_node_disk_size

      ami_type = "AL2023_x86_64_STANDARD"

      iam_role_name            = "tess-platform-node"
      iam_role_use_name_prefix = false

      labels = {
        role = "platform"
      }
    }
  }

  # Managed via explicit access_entries below so access doesn't depend
  # on which IAM identity runs terraform
  enable_cluster_creator_admin_permissions = false

  # Access entries:
  #   - eks_deployer role: primary access path (users assume this role)
  #   - <AWS_IAM_USER>: direct access for terraform providers (bootstrap)
  access_entries = {
    eks_deployer_role = {
      principal_arn = aws_iam_role.eks_deployer.arn
      policy_associations = {
        admin = {
          policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
          access_scope = {
            type = "cluster"
          }
        }
      }
    }
    # Direct access for terraform providers — remove after migrating
    # providers to assume_role
    terraform_user = {
      principal_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/<AWS_IAM_USER>"
      policy_associations = {
        admin = {
          policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
          access_scope = {
            type = "cluster"
          }
        }
      }
    }
  }

  # Node security group rules
  node_security_group_additional_rules = {
    ingress_vpc_all = {
      type        = "ingress"
      protocol    = "-1"
      from_port   = 0
      to_port     = 0
      cidr_blocks = [var.vpc_cidr]
      description = "Allow all ingress from VPC CIDR for pod-to-pod traffic"
    }
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
# gp3 StorageClass (default for platform tools PVCs)
# -----------------------------------------------------------------------------
resource "kubernetes_storage_class" "gp3" {
  metadata {
    name = "gp3"
    annotations = {
      "storageclass.kubernetes.io/is-default-class" = "true"
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
