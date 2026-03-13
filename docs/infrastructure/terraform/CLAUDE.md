# Terraform Agent Context

Quick reference for Terraform infrastructure management.

## File Locations

**AWS environment stack**: `k8s/terraform/aws/`
**Shared platform stack**: `k8s/terraform/shared/`

## Quick Commands

```bash
# Preferred: use aws-deploy.sh helper script
./scripts/aws-deploy.sh init production     # Initialize with production backend
./scripts/aws-deploy.sh plan production     # Plan changes
./scripts/aws-deploy.sh apply production    # Apply changes

# Shared stack (ECR, platform EKS, Headscale)
./scripts/aws-deploy.sh init shared
./scripts/aws-deploy.sh plan shared
./scripts/aws-deploy.sh apply shared

# Manual (fallback)
cd k8s/terraform/aws
terraform init
terraform plan
terraform apply
terraform output
terraform destroy  # DANGEROUS
```

## Common Tasks

### Update Node Count

1. Edit `terraform.tfvars`:
```hcl
eks_node_desired_size = 3
```

2. Apply:
```bash
terraform apply
```

### Add ECR Repository

1. Edit `ecr.tf`, add resource
2. Apply:
```bash
terraform apply
```

### View Resource Details

```bash
# List all resources
terraform state list

# Show specific resource
terraform state show aws_eks_cluster.main

# View outputs
terraform output cluster_name
```

## Best Practices

1. Always `terraform plan` before `apply`
2. Back up terraform.tfstate before major changes
3. Never commit .tfstate or .tfvars to git
4. Use AWS `<AWS_IAM_USER>` user for operations

## Critical Files

### AWS Environment Stack (`k8s/terraform/aws/`)
- `main.tf`: Provider configuration
- `eks.tf`: Cluster, nodes, addons (CoreDNS, kube-proxy), `eks-deployer` IAM role
- `ecr.tf`: ECR URL locals (repos managed by shared stack)
- `s3.tf`: Project storage
- `iam.tf`: IAM roles including `eks-deployer` with EKS access policy
- `kubernetes.tf`: K8s resources, secrets (including DISCORD_WEBHOOK_URL, AGENT_DISCORD_WEBHOOK_URL, TAVILY_API_KEY)
- `terraform.{env}.tfvars`: Your values (gitignored, stored in AWS Secrets Manager)

### Shared Platform Stack (`k8s/terraform/shared/`)
- `ecr.tf`: ECR repositories (shared across all environments)
- `eks.tf`: Platform EKS cluster for internal tools (Headscale VPN)
- `helm.tf`: NGINX Ingress, cert-manager, EBS CSI driver
- `headscale.tf`: Headscale VPN server with Litestream SQLite replication
- `dns.tf`: Cloudflare DNS management
- `s3.tf`: S3 buckets for Headscale state
- `iam.tf`: EKS deployer role, IRSA roles for node groups

See [shared.md](shared.md) for full documentation.

Environment stacks reference ECR via `local.ecr_*_url` locals (computed from account ID + region). See [ecr.md](ecr.md).
