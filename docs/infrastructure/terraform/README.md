# Terraform Infrastructure

Infrastructure as Code for AWS EKS deployment.

**Location**: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/terraform/aws/`

## Overview

Terraform provisions all AWS resources for Tesslate Studio production deployment:
- EKS cluster with managed node groups
- ECR repositories for container images
- S3 bucket for project storage
- VPC with public/private subnets
- IAM roles and policies
- Security groups

## Structure

```
k8s/terraform/aws/
├── main.tf                  # Provider and locals
├── variables.tf             # Input variables
├── outputs.tf               # Output values
├── vpc.tf                   # VPC, subnets, NAT gateway
├── eks.tf                   # EKS cluster, node groups, IRSA
├── ecr.tf                   # Container registries
├── s3.tf                    # Project storage bucket
├── iam.tf                   # IAM roles for pods
├── helm.tf                  # Helm charts (ingress, cert-manager)
├── kubernetes.tf            # K8s resources (storage class, namespaces)
└── terraform.tfvars         # Variable values (gitignored)
```

## Prerequisites

### Tools

```bash
# Terraform
brew install terraform  # macOS
choco install terraform  # Windows

# AWS CLI
brew install awscli  # macOS
choco install awscli  # Windows

# kubectl
brew install kubernetes-cli  # macOS
choco install kubernetes-cli  # Windows
```

### AWS Credentials

Use `<AWS_IAM_USER>` IAM user for deployments:

```bash
aws configure
# AWS Access Key ID: [from <AWS_IAM_USER> user]
# AWS Secret Access Key: [from <AWS_IAM_USER> user]
# Default region: us-east-1
# Default output format: json
```

**Permissions Required**:
- Full access to EKS, ECR, S3, VPC, IAM
- See terraform/aws/iam.tf for detailed policies

## Initial Setup

### 1. Clone and Navigate

```bash
cd k8s/terraform/aws
```

### 2. Create terraform.tfvars

```bash
cp terraform.tfvars.example terraform.tfvars
nano terraform.tfvars
```

**Required Variables**:
```hcl
# Project
project_name = "tesslate"
environment  = "production"

# Domain
domain_name = "your-domain.com"

# EKS
eks_cluster_version = "1.28"
eks_node_instance_types = ["t3.large"]
eks_node_min_size = 1
eks_node_max_size = 10
eks_node_desired_size = 2

# VPC
vpc_cidr = "10.0.0.0/16"
availability_zones = ["us-east-1a", "us-east-1b"]

# S3
s3_bucket_prefix = "tesslate-projects"
s3_force_destroy = false  # Prevent accidental deletion

# Tags
tags = {
  Project     = "Tesslate Studio"
  Environment = "Production"
  ManagedBy   = "Terraform"
}
```

### 3. Initialize Terraform

```bash
terraform init
```

Downloads providers:
- AWS provider
- Kubernetes provider
- Helm provider

### 4. Plan Changes

```bash
terraform plan
```

Review proposed changes before applying.

### 5. Apply Infrastructure

```bash
terraform apply
```

**Duration**: ~15-20 minutes
- VPC: ~2 min
- EKS cluster: ~10-15 min
- Node groups: ~3-5 min
- Add-ons and Helm charts: ~2-3 min

### 6. Configure kubectl

```bash
aws eks update-kubeconfig --region us-east-1 --name <EKS_CLUSTER_NAME>
```

### 7. Verify Deployment

```bash
# Check nodes
kubectl get nodes

# Check namespaces
kubectl get ns

# Check storage class
kubectl get storageclass tesslate-block-storage
```

## Resource Details

### VPC (vpc.tf)

**CIDR**: 10.0.0.0/16

**Subnets**:
- Public: 10.0.0.0/24, 10.0.1.0/24 (for NAT gateway, load balancers)
- Private: 10.0.10.0/24, 10.0.11.0/24 (for EKS nodes)

**NAT Gateway**: One per AZ (high availability)

**Internet Gateway**: For public subnet access

### EKS Cluster (eks.tf)

See [eks.md](eks.md) for detailed documentation.

**Version**: 1.28 (upgradeable)

**Node Groups**:
1. **Primary** (on-demand): t3.large, 1-10 nodes, desired 2
2. **Spot** (optional): t3.large/xlarge spot instances

**Addons**:
- CoreDNS (DNS resolution)
- kube-proxy (networking)
- VPC CNI (pod networking)
- EBS CSI Driver (block storage)

**IRSA Enabled**: IAM roles for service accounts

### ECR Repositories (ecr.tf)

See [ecr.md](ecr.md) for detailed documentation.

**Repositories**:
1. `tesslate-backend`
2. `tesslate-frontend`
3. `tesslate-devserver`

**Features**:
- Image scanning on push
- AES256 encryption
- Lifecycle policies (keep 30 tagged, 10 any, delete old untagged)

### S3 Bucket (s3.tf)

See [s3.md](s3.md) for detailed documentation.

**Name**: `tesslate-projects-production-{random-suffix}`

**Features**:
- Versioning enabled
- AES256 encryption
- Public access blocked
- Lifecycle rules (old versions → IA → Glacier → expire)
- CORS for frontend uploads

### IAM Roles (iam.tf)

**Backend Service Account Role**:
- Allows: S3 read/write to project bucket
- Attached to: `tesslate-backend-sa` in `tesslate` namespace

**EBS CSI Driver Role**:
- Allows: EBS volume creation/attachment
- Attached to: `ebs-csi-controller-sa` in `kube-system` namespace

**VPC CNI Role**:
- Allows: ENI management for pod networking
- Attached to: `aws-node` in `kube-system` namespace

## Modifying Infrastructure

### Change Node Group Size

1. Edit terraform.tfvars:
```hcl
eks_node_desired_size = 3  # Was 2
```

2. Apply changes:
```bash
terraform apply
```

### Upgrade EKS Version

1. Edit terraform.tfvars:
```hcl
eks_cluster_version = "1.29"  # Was 1.28
```

2. Apply changes (control plane first):
```bash
terraform apply
```

3. Upgrade node groups (manual or gradual):
```bash
# Drain and replace nodes one by one
kubectl drain {node-name} --ignore-daemonsets --delete-emptydir-data
# Terraform will create new nodes with new version
```

### Add New ECR Repository

1. Edit ecr.tf:
```hcl
resource "aws_ecr_repository" "my_new_repo" {
  name = "${var.project_name}-my-new-repo"
  image_tag_mutability = "MUTABLE"
  # ... rest of config
}
```

2. Apply:
```bash
terraform apply
```

## State Management

**Backend**: Local (terraform.tfstate file)

**Warning**: .tfstate contains sensitive data, never commit to git!

**Future**: Use remote backend for team collaboration:
```hcl
# main.tf
terraform {
  backend "s3" {
    bucket = "<TERRAFORM_STATE_BUCKET>"
    key    = "aws/terraform.tfstate"
    region = "us-east-1"
    encrypt = true
    dynamodb_table = "<AWS_IAM_USER>-locks"
  }
}
```

## Outputs

After `terraform apply`, useful outputs are displayed:

```bash
cluster_name = "<EKS_CLUSTER_NAME>"
cluster_endpoint = "https://xxx.eks.us-east-1.amazonaws.com"
ecr_backend_url = "<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend"
ecr_frontend_url = "<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-frontend"
ecr_devserver_url = "<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-devserver"
s3_bucket_name = "tesslate-projects-production-7761157a"
vpc_id = "vpc-xxx"
```

Access outputs anytime:
```bash
terraform output
terraform output cluster_name
```

## Cost Estimation

**EKS Cluster**: $0.10/hour = $73/month
**EC2 Nodes** (2 × t3.large): $0.0832/hour × 2 × 730 = $121/month
**EBS Volumes**: $0.10/GB/month × 100GB = $10/month
**S3 Storage**: $0.023/GB/month × 10GB = $0.23/month
**NAT Gateway**: $0.045/hour × 2 = $66/month
**Data Transfer**: Variable (~$10-50/month)

**Total**: ~$280-320/month for baseline infrastructure

**Cost Optimization**:
- Use spot instances for dev containers (90% savings)
- Autoscaling (scale down during off-hours)
- S3 lifecycle policies (move old data to Glacier)
- EBS gp3 instead of gp2 (20% cheaper)

## Disaster Recovery

### Backup State File

```bash
cp terraform.tfstate terraform.tfstate.backup
```

### Export EKS Resources

```bash
kubectl get all --all-namespaces -o yaml > k8s-backup.yaml
```

### Recreate from Scratch

1. Ensure terraform.tfstate is backed up
2. Run `terraform destroy` (if needed)
3. Run `terraform apply`
4. Redeploy applications: `kubectl apply -k k8s/overlays/aws`

## Troubleshooting

### Provider Version Conflicts

**Symptom**: `inconsistent dependency lock file`

**Fix**:
```bash
terraform init -upgrade
```

### State Lock

**Symptom**: `state is locked`

**Fix**: Wait for other operation to complete, or force unlock:
```bash
terraform force-unlock {lock-id}
```

### Resource Already Exists

**Symptom**: `resource already exists`

**Fix**: Import existing resource:
```bash
terraform import aws_eks_cluster.main <EKS_CLUSTER_NAME>
```

### EKS Cluster Creation Timeout

**Symptom**: Cluster stuck in CREATING for >20 min

**Check CloudTrail**: Look for API errors

**Fix**: May need to increase IAM limits or change instance type

## Cleanup

### Destroy All Resources

**WARNING**: This deletes ALL infrastructure!

```bash
terraform destroy
```

**Note**: S3 bucket with `force_destroy = false` must be emptied manually first:
```bash
aws s3 rm s3://tesslate-projects-production-{suffix} --recursive
```

### Selective Destroy

```bash
# Destroy specific resource
terraform destroy -target=aws_eks_cluster.main

# Destroy module
terraform destroy -target=module.eks
```

## Best Practices

1. **Always plan first**: Review changes before apply
2. **Use variables**: Never hardcode values
3. **Tag resources**: Use consistent tagging for cost tracking
4. **State backup**: Back up terraform.tfstate regularly
5. **Use modules**: DRY principle (we use AWS modules)
6. **Version control**: .tfstate in .gitignore, .tfvars in .gitignore
7. **Separate environments**: Use workspaces or separate directories

## Related Documentation

- [eks.md](eks.md): EKS cluster configuration
- [ecr.md](ecr.md): Container registry
- [s3.md](s3.md): Project storage
- Terraform AWS Provider: https://registry.terraform.io/providers/hashicorp/aws/latest/docs
