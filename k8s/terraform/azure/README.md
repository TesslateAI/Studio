# OpenSail — Azure AKS Terraform

Mirrors `k8s/terraform/aws` for Azure as a full-featured deployment platform.

## What this stack provisions

| Layer | AWS equivalent | Resource |
|---|---|---|
| Compute | EKS + managed node groups | `azurerm_kubernetes_cluster` + system / user / spot node pools |
| Pod identity | IRSA | AKS Workload Identity (`azurerm_user_assigned_identity` + `azurerm_federated_identity_credential`) |
| Network | VPC + subnets + NAT GW | `azurerm_virtual_network` + delegated subnets, Standard LB egress |
| Storage (object) | S3 buckets ×3 | `azurerm_storage_account` + 3 Blob containers |
| Storage (block) | EBS gp3 StorageClass | Azure Disk Premium SSD StorageClass (via overlay) |
| Registry | ECR | `azurerm_container_registry` (ACR) |
| Database | RDS Postgres | `azurerm_postgresql_flexible_server` |
| Cache | ElastiCache Redis | `azurerm_redis_cache` |
| Secrets / KMS | AWS Secrets Manager | `azurerm_key_vault` (RBAC mode, soft-delete + purge-protection on prod) |
| DNS | Cloudflare (NLB hostname) | Cloudflare (Standard LB IP — A records, not CNAMEs) |
| TLS | cert-manager + Cloudflare DNS01 | cert-manager + Cloudflare DNS01 (identical) |
| Ingress | NGINX | NGINX (identical, different `service.beta.kubernetes.io/*` annotations) |
| Reflector / Snapshot ctrl | emberstack/reflector + piraeus snapshot-controller | identical |

## Bootstrap (one-time, out-of-band)

The terraform backend stores state in a Storage Account that has to exist before
`terraform init` runs. Create it once per cloud account:

```bash
RG=tesslate-tfstate-rg
SA=tesslatetfstate           # globally unique, lowercase, 3-24 chars
LOC=eastus

az group create -n "$RG" -l "$LOC"
az storage account create -n "$SA" -g "$RG" -l "$LOC" \
  --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2
az storage container create -n tfstate --account-name "$SA"
```

## Deploy

```bash
# Beta — fetch tfvars from Key Vault first if you don't have it locally
./scripts/terraform/azure-secrets.sh download beta

cd k8s/terraform/azure
terraform init -backend-config=backend-beta.hcl
terraform apply -var-file=terraform.beta.tfvars
```

Or use the wrapper script:

```bash
./scripts/azure-deploy.sh terraform beta
./scripts/azure-deploy.sh deploy-k8s beta
./scripts/azure-deploy.sh build beta
```

## Where state and secrets live

| Artifact | Backend | How to access |
|---|---|---|
| `terraform.tfstate` per env | Azure Blob Storage container `tfstate` in the bootstrap SA | terraform auto-reads/writes via `backend-{env}.hcl`; lock blob held automatically |
| `terraform.{env}.tfvars` (Cloudflare token, Postgres password, app secret, etc.) | Azure Key Vault `tesslate-{env-short}-{suffix}`, secret name `<AWS_IAM_USER>-{env}` | `./scripts/terraform/azure-secrets.sh {download,upload,view,versions} {env}` |
| K8s Secrets in cluster | Cluster etcd (encrypted at rest by AKS) | terraform-managed `kubernetes_secret` resources, written on every apply |

**Both are durable on Azure.** A fresh machine only needs `az login`, the
bootstrap RG/SA names, and the AAD admin group object id to recover the
full env. The Key Vault is created and managed by `keyvault.tf` in this
stack — first apply needs the tfvars locally (chicken-and-egg with the
vault), every subsequent apply can pull from KV.

To rotate a secret (e.g. Cloudflare token): edit `terraform.{env}.tfvars`
locally, `terraform apply`, then `./scripts/terraform/azure-secrets.sh
upload {env}` to push the new value to KV. Previous versions are kept
30 days by default.

## AAD prereqs

You need at least one Azure AD group object ID in `aks_admin_group_object_ids` —
this group gets the AKS RBAC Cluster Admin role.

```bash
# Create a team admin group
az ad group create --display-name tesslate-prod-admins --mail-nickname tesslate-prod-admins
az ad group show --group tesslate-prod-admins --query id -o tsv
```

Add yourself before applying.

## Where things differ from AWS

- **No spot Fargate equivalent** — Azure Container Instances via Virtual Nodes
  is the closest analogue but adds latency and is not wired in here. CoreDNS
  runs on the system pool.
- **IRSA → Workload Identity** — Pods opt in via the `azure.workload.identity/use: "true"`
  label (set in the overlays). Federated credential subjects bind the K8s SA
  to the UAMI.
- **State backend** — `azurerm` instead of `s3`. Same per-env `key`.
- **DNS** — Standard LB returns an IP, so we create A records (AWS creates
  CNAMEs because NLB exposes a hostname).
- **Postgres SSL** — Flexible Server requires `ssl=require` (or `sslmode=require`).
  Already added to `database_url` in `kubernetes.tf`.
- **Storage access** — `boto3` + S3-compatible Blob endpoint. Workload Identity
  supplies the AAD token through the federation flow. For regions without S3
  compat, swap the btrfs CSI driver to `STORAGE_PROVIDER=azureblob` (rclone
  azureblob backend) — same secret shape, different keys.
