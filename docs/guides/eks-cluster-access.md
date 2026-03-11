# EKS Cluster Access via eks-deployer IAM Role

## Overview

EKS cluster access uses a **role-based model** instead of granting individual IAM users direct cluster permissions. A dedicated `eks-deployer` IAM role is registered as an EKS access entry with `AmazonEKSClusterAdminPolicy`. Users who need `kubectl` access assume this role.

### Why Role-Based Access?

- **Decoupled permissions**: Adding/removing users doesn't touch EKS access entries or require `terraform apply` on the cluster
- **Single control point**: The role's trust policy is the source of truth for who has cluster access
- **Auditability**: CloudTrail logs show which user assumed the role
- **CI/CD friendly**: GitHub Actions or other automation can assume the same role

## Architecture

```
                    ┌──────────────────────────────┐
                    │   EKS Access Entry            │
                    │   (ClusterAdmin)              │
                    │                               │
                    │   Principal: eks-deployer role │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────┴───────────────┐
                    │   IAM Role                    │
                    │   tesslate-{env}-eks-deployer │
                    │                               │
                    │   Trust Policy:               │
                    │     eks_admin_iam_arns        │
                    └──────────────┬───────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                     │
     ┌────────┴────────┐  ┌───────┴────────┐  ┌────────┴────────┐
     │ IAM User:       │  │ IAM User:      │  │ IAM User:       │
     │ tesslate-       │  │ tesslate-      │  │ (future users)  │
     │ terraform       │  │ bigboss        │  │                 │
     └─────────────────┘  └────────────────┘  └─────────────────┘
```

## How It Works

### Terraform Resources

| Resource | File | Purpose |
|----------|------|---------|
| `aws_iam_role.eks_deployer` | `k8s/terraform/aws/iam.tf` | The role that has EKS cluster admin access |
| `variable "eks_admin_iam_arns"` | `k8s/terraform/aws/variables.tf` | List of IAM ARNs allowed to assume the role |
| EKS `access_entries.eks_deployer_role` | `k8s/terraform/aws/eks.tf` | Grants the role `AmazonEKSClusterAdminPolicy` |
| `output "eks_deployer_role_arn"` | `k8s/terraform/aws/outputs.tf` | Outputs the role ARN for scripts |

### aws-deploy.sh Integration

The `ensure_kubectl_context()` function in `scripts/aws-deploy.sh` automatically assumes the eks-deployer role when configuring kubectl:

```bash
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${CLUSTER_NAME}-eks-deployer"
aws eks update-kubeconfig --name "$CLUSTER_NAME" --role-arn "$ROLE_ARN"
```

This means all `aws-deploy.sh` subcommands that touch the cluster (`deploy-k8s`, `build`, `reload`) use role-based access automatically.

## Adding a User to the Admin List

### Step 1: Get the user's IAM ARN

The ARN format is:
```
arn:aws:iam::<AWS_ACCOUNT_ID>:user/<username>
```

For an IAM role (e.g., CI/CD):
```
arn:aws:iam::<AWS_ACCOUNT_ID>:role/<role-name>
```

### Step 2: Download the tfvars file for the target environment

Each environment (production, beta) has its own `eks_admin_iam_arns` list in its tfvars file. You must update each environment separately.

```bash
# Download the tfvars from AWS Secrets Manager
./scripts/terraform/secrets.sh download production
./scripts/terraform/secrets.sh download beta
```

This creates:
- `k8s/terraform/aws/terraform.production.tfvars`
- `k8s/terraform/aws/terraform.beta.tfvars`

### Step 3: Edit the tfvars file

Add the user's ARN to `eks_admin_iam_arns` in each environment's tfvars:

**Production** (`k8s/terraform/aws/terraform.production.tfvars`):
```hcl
eks_admin_iam_arns = [
  "arn:aws:iam::<AWS_ACCOUNT_ID>:user/<AWS_IAM_USER>",
  "arn:aws:iam::<AWS_ACCOUNT_ID>:user/tesslate-bigboss",
  "arn:aws:iam::<AWS_ACCOUNT_ID>:user/new-team-member"    # <-- add here
]
```

**Beta** (`k8s/terraform/aws/terraform.beta.tfvars`):
```hcl
eks_admin_iam_arns = [
  "arn:aws:iam::<AWS_ACCOUNT_ID>:user/<AWS_IAM_USER>",
  "arn:aws:iam::<AWS_ACCOUNT_ID>:user/tesslate-bigboss",
  "arn:aws:iam::<AWS_ACCOUNT_ID>:user/new-team-member"    # <-- add here
]
```

> **Note**: The lists don't have to match. A user can have access to beta but not production, or vice versa.

### Step 4: Apply the Terraform changes

```bash
# Production
./scripts/aws-deploy.sh plan production     # Review changes — should only update the role's trust policy
./scripts/aws-deploy.sh apply production    # Apply (type "yes" to confirm)

# Beta
./scripts/aws-deploy.sh plan beta
./scripts/aws-deploy.sh apply beta
```

The plan output should show a change only to `aws_iam_role.eks_deployer` (updating `assume_role_policy`). No EKS access entries change.

### Step 5: Upload updated tfvars back to AWS Secrets Manager

```bash
./scripts/terraform/secrets.sh upload production
./scripts/terraform/secrets.sh upload beta
```

This ensures other team members get the updated list when they download.

### Step 6: New user configures kubectl

The new user runs:

```bash
# One-time setup: configure kubectl with role assumption
aws eks update-kubeconfig \
  --region us-east-1 \
  --name tesslate-production-eks \
  --role-arn arn:aws:iam::<AWS_ACCOUNT_ID>:role/tesslate-production-eks-eks-deployer

# Verify access
kubectl get nodes
```

Or they can use `aws-deploy.sh` directly, which handles role assumption automatically:

```bash
./scripts/aws-deploy.sh deploy-k8s production
./scripts/aws-deploy.sh build production backend
./scripts/aws-deploy.sh reload production
```

## Removing a User

1. Remove their ARN from `eks_admin_iam_arns` in the relevant tfvars files
2. Apply terraform for each environment
3. Upload tfvars to Secrets Manager

The user will immediately lose the ability to assume the role and access the cluster.

## Quick Reference

| Task | Command |
|------|---------|
| See current admin list | Check tfvars: `./scripts/terraform/secrets.sh production` |
| See role ARN | `./scripts/aws-deploy.sh output production \| grep eks_deployer_role_arn` |
| Verify your own access | `aws sts assume-role --role-arn <role-arn> --role-session-name test` |
| Check who can assume | `aws iam get-role --role-name tesslate-production-eks-eks-deployer` |

## Bootstrap Note

The `<AWS_IAM_USER>` IAM user has **both** a direct EKS access entry (in `eks.tf`) and is in the `eks_admin_iam_arns` list. The direct entry is a bootstrap mechanism — it ensures terraform can always reach the cluster even if the role doesn't exist yet (first `terraform apply`). Once all access is migrated to role-based, the direct entry can be removed.
