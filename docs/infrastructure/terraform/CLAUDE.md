# Terraform Agent Context

Quick reference for Terraform infrastructure management.

## File Locations

**AWS environment stack**: `k8s/terraform/aws/`
**Azure environment stack**: `k8s/terraform/azure/` (full-featured parity with the AWS stack — AKS + ACR + Storage Account + Postgres Flexible Server + Azure Cache for Redis + Workload Identity)
**Shared platform stack**: `k8s/terraform/shared/`

## Quick Commands

```bash
# AWS: use aws-deploy.sh helper script
./scripts/aws-deploy.sh init production     # Initialize with production backend
./scripts/aws-deploy.sh plan production     # Plan changes
./scripts/aws-deploy.sh apply production    # Apply changes

# Azure: use azure-deploy.sh — same subcommand surface as the AWS script.
# Scripts are intentionally separate so per-cloud changes can't bleed
# into the other.
./scripts/azure-deploy.sh init production
./scripts/azure-deploy.sh plan production
./scripts/azure-deploy.sh apply production

# Shared stack (ECR, platform EKS, Headscale) — AWS only
./scripts/aws-deploy.sh init shared
./scripts/aws-deploy.sh plan shared
./scripts/aws-deploy.sh apply shared

# Manual (fallback)
cd k8s/terraform/aws    # or k8s/terraform/azure
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

### Azure Environment Stack (`k8s/terraform/azure/`)

Mirrors the AWS layout 1:1, swapping cloud primitives. See `k8s/terraform/azure/README.md` for the full mapping table and bootstrap commands.

- `main.tf`: `azurerm` + `azuread` + `helm` + `kubectl` + `cloudflare` providers, locals (cluster_name, acr_name, image_tag), random suffix for globally-unique names
- `vnet.tf`: VNet + subnets (aks-nodes, postgres, redis) + Postgres private DNS zone
- `aks.tf`: AKS cluster with Workload Identity + OIDC issuer, system / user / spot node pools, AAD group RBAC role assignments (admin/deployer/observer/debugger), ACR pull
- `acr.tf`: Azure Container Registry (Premium in prod, Standard in beta) + quay pull-through cache
- `storage.tf`: Storage Account + three Blob containers (projects / btrfs-snapshots / marketplace-bundles) + lifecycle policy
- `iam.tf`: Three User-Assigned Managed Identities federated to K8s SAs — backend, btrfs-csi, volume-hub — plus cert-manager UAMI
- `postgres.tf`: Azure Postgres Flexible Server + databases (tesslate, tesslate_marketplace)
- `redis.tf`: Azure Cache for Redis (Standard/Premium)
- `helm.tf`: NGINX Ingress (Standard LB annotations), cert-manager, reflector, external-dns, metrics-server, snapshot-controller, btrfs VolumeSnapshotClass
- `kubernetes.tf`: Namespace, ServiceAccounts with Workload Identity annotations, Secrets, ConfigMaps, Wildcard Certificate, main Ingress, default NetworkPolicy
- `dns.tf`: Cloudflare A records (Standard LB returns IP, not hostname — A records, not CNAMEs)
- `outputs.tf`: cluster name, ACR login server, container names, UAMI client IDs, postgres/redis endpoints
- `backend-{beta,production}.hcl`: `azurerm` backend pointing at a Storage Account container (bootstrap commands in `README.md`)
- `terraform.tfvars.example`: full var set with Azure-specific defaults

Image references via `local.acr_*_url` locals (computed from `acr_name` + ACR login-server). Equivalent to the ECR locals in the AWS stack.
