# EKS Cluster Access

## Overview

EKS cluster access uses a **role-based model**. Users have zero AWS permissions on their own — they assume one of several IAM roles via `sts:AssumeRole`, and the role is registered as an EKS access entry that grants `kubectl` permission.

There are **two parallel access paths**:

1. **`eks-deployer` role** — cluster admin, gated by the static `eks_admin_iam_arns` list in tfvars. Used by terraform, CI/CD, and a few named humans (`<AWS_IAM_USER>`, `tesslate-bigboss`). **Do not add regular team members here.**
2. **Team roles** (`team-observer`, `team-deployer`, `team-debugger`, `team-admin`) — scoped roles per environment. Access is granted by **IAM group membership** (`tesslate-{env}-{observers,deployers,debuggers,admins}`), so onboarding/offboarding never requires `terraform apply`.

Most humans should be in one or more team groups and assume the matching team role. Only fall back to `eks-deployer` if you are explicitly listed in `eks_admin_iam_arns`.

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

---

# Team Roles (the normal path for humans)

If you are a regular team member (not `<AWS_IAM_USER>` / `tesslate-bigboss`), **you must assume one of the team roles** before any `aws` or `kubectl` command against beta or production. Your plain IAM user has no `eks:*` / `logs:*` / `ecr:*` permissions — those live on the role. Without assuming a role, every call fails with `AccessDenied` / "unable to describe cluster".

## Task → Role Mapping

Pick the least-privilege role that covers the task. Replace `{env}` with `beta` or `production`.

| I want to … | Role | ARN |
|---|---|---|
| `kubectl logs`, `kubectl get`, `kubectl describe`, read CloudWatch control-plane logs, browse ECR | **team-observer** | `arn:aws:iam::<AWS_ACCOUNT_ID>:role/tesslate-{env}-eks-team-observer` |
| Everything observer can do, plus `kubectl rollout`, restart/patch deployments, push to ECR | **team-deployer** | `arn:aws:iam::<AWS_ACCOUNT_ID>:role/tesslate-{env}-eks-team-deployer` |
| Everything deployer can do, plus `kubectl exec`, shell into pods, run debug containers | **team-debugger** | `arn:aws:iam::<AWS_ACCOUNT_ID>:role/tesslate-{env}-eks-team-debugger` |
| Everything above, plus Secrets Manager, RBAC, namespace mgmt, create/destroy IAM team users | **team-admin** | `arn:aws:iam::<AWS_ACCOUNT_ID>:role/tesslate-{env}-eks-team-admin` |

Hierarchy (from `k8s/terraform/aws/eks.tf:208-228`):
- `team_deployer` is mapped to K8s groups `tesslate:observers + tesslate:deployers`
- `team_debugger` is mapped to `tesslate:observers + tesslate:deployers + tesslate:debuggers`
- `team_admin` is mapped to the full `AmazonEKSClusterAdminPolicy`

So a debugger can read logs without also assuming observer — one role covers the stack below it.

## How to Actually Use a Team Role

### Option A: One-shot assume-role (good for Claude / ad-hoc shells)

```bash
# 1. Assume the role and export temp creds into the current shell.
eval "$(aws sts assume-role \
  --role-arn arn:aws:iam::<AWS_ACCOUNT_ID>:role/tesslate-beta-eks-team-debugger \
  --role-session-name $(whoami)-$(date +%s) \
  --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' --output text \
  | awk '{printf "export AWS_ACCESS_KEY_ID=%s AWS_SECRET_ACCESS_KEY=%s AWS_SESSION_TOKEN=%s\n",$1,$2,$3}')"

# 2. Write the kubeconfig entry (only needed once per machine; re-run if the
#    cluster endpoint ever changes).
aws eks update-kubeconfig --region us-east-1 --name tesslate-beta-eks --alias tesslate-beta-eks

# 3. All kubectl/aws calls in this shell now use the assumed role.
kubectl --context=tesslate-beta-eks logs -n tesslate deploy/tesslate-backend --tail=200
aws logs tail /aws/eks/tesslate-beta-eks/cluster --since 15m
```

Temp creds expire after 1 hour by default; re-run step 1 when that happens.

### Option B: Named AWS CLI profile (good for daily drivers)

Add to `~/.aws/config`:

```ini
# Your long-lived IAM user creds live under this profile's access key/secret.
[profile tesslate-me]
region = us-east-1

# One profile per (env, role) you commonly use.
[profile tesslate-beta-observer]
role_arn       = arn:aws:iam::<AWS_ACCOUNT_ID>:role/tesslate-beta-eks-team-observer
source_profile = tesslate-me
region         = us-east-1

[profile tesslate-beta-debugger]
role_arn       = arn:aws:iam::<AWS_ACCOUNT_ID>:role/tesslate-beta-eks-team-debugger
source_profile = tesslate-me
region         = us-east-1

[profile tesslate-prod-observer]
role_arn       = arn:aws:iam::<AWS_ACCOUNT_ID>:role/tesslate-production-eks-team-observer
source_profile = tesslate-me
region         = us-east-1

[profile tesslate-prod-debugger]
role_arn       = arn:aws:iam::<AWS_ACCOUNT_ID>:role/tesslate-production-eks-team-debugger
source_profile = tesslate-me
region         = us-east-1
```

Then just:

```bash
export AWS_PROFILE=tesslate-beta-debugger
aws eks update-kubeconfig --region us-east-1 --name tesslate-beta-eks --alias tesslate-beta-eks
kubectl --context=tesslate-beta-eks logs -n tesslate deploy/tesslate-backend --tail=200
```

The CLI handles `AssumeRole` automatically on every API call.

## Onboarding a New Team Member

```bash
# 1. Create the IAM user under /team/ path (path matters — admin policy scopes to it).
aws iam create-user --user-name tesslate-alice --path /team/
aws iam create-access-key --user-name tesslate-alice

# 2. Add them to the group(s) they need, per environment.
aws iam add-user-to-group --user-name tesslate-alice --group-name tesslate-beta-debuggers
aws iam add-user-to-group --user-name tesslate-alice --group-name tesslate-production-observers

# 3. Hand them the access key + the Option B config block above.
```

No `terraform apply` needed. Remove access with `aws iam remove-user-from-group`.

## Common Failure Modes

| Symptom | Cause | Fix |
|---|---|---|
| `unable to describe cluster` / `AccessDenied: eks:DescribeCluster` | You ran `aws eks describe-cluster` or `aws eks update-kubeconfig` as the raw user without assuming a role. | Assume a team role first (Option A or B). |
| `User ... is not authorized to perform: sts:AssumeRole on resource ...team-debugger` | Your IAM user isn't in the `tesslate-{env}-debuggers` group (or higher). | `aws iam add-user-to-group --user-name <you> --group-name tesslate-{env}-debuggers` |
| `error: You must be logged in to the server (Unauthorized)` when running kubectl | kubeconfig was built **without** `--role-arn` (so it resolves to raw user), and your raw user has no EKS access entry. | Re-run `aws eks update-kubeconfig` **while** the assumed role's creds are active. The resulting kubeconfig bakes in the role. |
| `./scripts/aws-deploy.sh ...` fails with "Can you assume role ...team-admin?" | Your IAM user isn't in `tesslate-{env}-admins`. The script defaults to `team-admin` so `deploy-k8s` / `deploy-compute` work out of the box. | Pass `--role deployer` (or `observer`/`debugger`) to drop down to a role you can assume — e.g. `./scripts/aws-deploy.sh build production --role deployer`. For cross-account or legacy `eks-deployer`, set `AWS_EKS_ROLE_ARN=arn:aws:iam::<AWS_ACCOUNT_ID>:role/...` before invoking. |
