# Terraform Module Index

Per-file reference for every `.tf` file in `k8s/terraform/aws/` (environment stack) and `k8s/terraform/shared/` (platform stack). See `eks.md`, `ecr.md`, `s3.md`, `shared.md` for deep dives on the named modules.

## AWS environment stack (`k8s/terraform/aws/`)

| File | Purpose |
|------|---------|
| `main.tf` | Terraform providers (AWS, Kubernetes, Helm, kubectl, Cloudflare). Locals: region, account id, env, naming prefixes. |
| `variables.tf` | Input variables (env name, domain, node sizing, RDS size, image tags, Cloudflare zone). |
| `outputs.tf` | Cluster name + endpoint, ECR URLs (computed), S3 bucket, Route 53 zone, NLB hostname, kubeconfig block. |
| `vpc.tf` | VPC, public + private subnets across pinned AZs, NAT gateways, route tables, S3 + ECR VPC endpoints. |
| `eks.tf` | EKS cluster, managed node groups (pinned to `eks_node_azs`), addons (CoreDNS, kube-proxy, VPC-CNI, EBS CSI), `eks-deployer` IAM role. See `eks.md`. |
| `ecr.tf` | ECR URL locals only; repositories are managed by the shared stack. See `ecr.md`. |
| `s3.tf` | Project storage bucket, lifecycle rules, access logging, IAM policy documents. See `s3.md`. |
| `iam.tf` | IAM roles: backend IRSA, worker IRSA, cluster autoscaler, ebs-csi-controller, `eks-deployer` with EKS access policy. |
| `elasticache.tf` | Redis 7.x ElastiCache (single node or replication group), subnet group, security group, parameter group. |
| `helm.tf` | Helm releases in the workload cluster: NGINX Ingress, cert-manager, ExternalDNS (optional), metrics-server if missing. |
| `kubernetes.tf` | K8s resources created by Terraform: `tesslate` namespace labels, `tesslate-app-secrets`, `postgres-secret`, `s3-credentials`, `frontend-config` ConfigMap, image pull secret (if any). |
| `dns.tf` | Cloudflare DNS records: `{env}.tesslate.com`, `*.opensail.tesslate.com`, MX / TXT. |
| `litellm.tf` | LiteLLM proxy Deployment + Service + ConfigMap mount (`../../litellm/config.yaml`). |
| `terraform.production.tfvars` | Production values (gitignored replicas + secrets pulled from AWS Secrets Manager). |
| `terraform.beta.tfvars` | Beta values. |
| `terraform.tfvars.example` | Template. |
| `backend-production.hcl` | S3 backend config for production state (`<TERRAFORM_STATE_BUCKET>-production`). |
| `backend-beta.hcl` | Same for beta. |
| `README.md` | Stack quickstart. |

## Shared platform stack (`k8s/terraform/shared/`)

Runs once; feeds both beta and production with platform-wide resources.

| File | Purpose |
|------|---------|
| `main.tf` | Providers and shared locals. |
| `variables.tf` | Cloudflare token, domain, ECR repo names, Headscale config. |
| `outputs.tf` | ECR URLs, platform cluster endpoint, Headscale URL, Litestream bucket name. |
| `vpc.tf` | Platform VPC separate from environment VPCs; peered for CI runners if needed. |
| `eks.tf` | Platform EKS (tooling + Headscale). |
| `ecr.tf` | ECR repositories: `tesslate-backend`, `tesslate-frontend`, `tesslate-devserver`, `tesslate-btrfs-csi`. Lifecycle policies. Shared across all environment stacks. |
| `iam.tf` | `eks-deployer` role, IRSA roles consumed by the platform cluster. |
| `s3.tf` | Buckets for Headscale litestream replication, Terraform state (for the environment stacks), build cache. |
| `helm.tf` | NGINX Ingress controller, cert-manager, EBS CSI driver, external-dns (for Cloudflare). |
| `headscale.tf` | Headscale VPN: Deployment with init container `litestream restore`, main `headscale`, sidecar `litestream replicate` -> S3. |
| `dns.tf` | Cloudflare DNS for the platform cluster (Headscale hostname, ingress NLB CNAME). |
| `backend.hcl` | S3 backend config for the shared stack state. |
| `terraform.tfvars.example` | Template. |

## Workflow

```bash
# Shared (ECR, platform EKS, Headscale): run once, then only when platform changes
./scripts/aws-deploy.sh init shared
./scripts/aws-deploy.sh plan shared
./scripts/aws-deploy.sh apply shared

# Per-environment: run per deployment target
./scripts/aws-deploy.sh init production
./scripts/aws-deploy.sh plan production
./scripts/aws-deploy.sh apply production
```

## envFrom contract

`kubernetes.tf` creates `tesslate-app-secrets`, `postgres-secret`, and `s3-credentials`. Every key added to those secrets is auto-mounted into the backend via `envFrom` in the AWS overlay. Adding a new config key means:

1. Add it to the Terraform secret in `kubernetes.tf`.
2. Re-apply the stack.
3. Restart the backend deployment.

No kustomize edit is needed. See `docs/infrastructure/CLAUDE.md` "AWS Overlay: envFrom Auto-Sync".
