# Terraform Agent Context

Quick reference for Terraform infrastructure management.

## File Locations

**Terraform files**: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/terraform/aws/`

## Quick Commands

```bash
# Navigate
cd k8s/terraform/aws

# Initialize
terraform init

# Plan changes
terraform plan

# Apply changes
terraform apply

# View outputs
terraform output

# Destroy (DANGEROUS)
terraform destroy
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

- `main.tf`: Provider configuration
- `eks.tf`: Cluster and nodes
- `ecr.tf`: Container registries
- `s3.tf`: Project storage
- `terraform.tfvars`: Your values (gitignored)
