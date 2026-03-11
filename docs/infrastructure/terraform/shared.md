# Shared Platform Stack

The shared Terraform stack manages infrastructure that is independent of production/beta environments: ECR repositories (shared image registry), the platform EKS cluster, and all platform tools (Headscale VPN).

**Location**: `k8s/terraform/shared/`

## Architecture

```
                       Tailscale Clients
                             |
                             v
Cloudflare DNS --CNAME--> AWS NLB
                             |
                             v
+----------------------------------------------+
|  EKS Platform Cluster                        |
|                                              |
|  +----------------------------------------+  |
|  | NGINX Ingress Controller               |  |
|  +--------------------+-------------------+  |
|                       |                      |
|                       v                      |
|  +----------------------------------------+  |
|  | Headscale Pod                          |  |
|  |   init: litestream restore             |  |
|  |   main: headscale server               |  |
|  |   sidecar: litestream replicate -------+--+--> S3
|  +----------------------------------------+  |
|                                              |
|  cert-manager <-- Let's Encrypt              |
+----------------------------------------------+

+----------------------------------------------+
|  ECR (shared across prod/beta)               |
|    tesslate-backend                          |
|    tesslate-frontend                         |
|    tesslate-devserver                        |
+----------------------------------------------+
```

See [shared-platform.mmd](../../architecture/diagrams/shared-platform.mmd) for the detailed Mermaid diagram.

## Overview

```
k8s/terraform/shared/
├── main.tf                  # Providers (AWS, K8s, Helm, Kubectl, Cloudflare), locals
├── variables.tf             # Input variables (all with defaults except Cloudflare secrets)
├── outputs.tf               # ECR URLs, cluster info, Headscale URL, Litestream bucket
├── backend.hcl              # S3 state backend config
├── terraform.tfvars.example # Template for variable values
├── ecr.tf                   # ECR repositories (backend, frontend, devserver)
├── vpc.tf                   # Isolated VPC (10.1.0.0/16), single NAT gateway
├── eks.tf                   # Platform EKS cluster, single ON_DEMAND node group, gp3 StorageClass
├── iam.tf                   # EKS deployer role, IRSA roles (VPC CNI, EBS CSI, cert-manager, Headscale)
├── helm.tf                  # NGINX Ingress Controller, cert-manager, ClusterIssuer
├── dns.tf                   # Cloudflare CNAME records for platform tools
├── headscale.tf             # Headscale VPN (native K8s resources) with Litestream SQLite replication
└── s3.tf                    # S3 bucket for Litestream WAL replicas
```

## Components

### ECR Repositories (`ecr.tf`)

Shared container image registry used by both production and beta environments. Each environment pushes different tags (`:production`, `:beta`) to the same repos.

| Repository | Purpose |
|------------|---------|
| `tesslate-backend` | Orchestrator API |
| `tesslate-frontend` | React frontend |
| `tesslate-devserver` | User project containers |

### Platform VPC (`vpc.tf`)

Fully isolated VPC — no shared resources with production/beta VPCs.

| Setting | Value |
|---------|-------|
| CIDR | `10.1.0.0/16` |
| Subnets | 3 public + 3 private (across 3 AZs) |
| NAT Gateway | Single (cost optimization) |
| DNS | Hostnames + support enabled |

### Platform EKS Cluster (`eks.tf`)

Minimal EKS cluster for running internal tools.

| Setting | Value |
|---------|-------|
| Name | `tesslate-platform-eks` |
| Node Group | Single ON_DEMAND `t3.medium` |
| Scaling | 1 min / 2 max / 1 desired |
| AMI | AL2023 x86_64 |
| Storage | gp3 StorageClass (default, encrypted) |
| Addons | CoreDNS, kube-proxy, VPC CNI, EBS CSI |
| Access | `eks-deployer` role (users assume via `eks_admin_iam_arns`) + `<AWS_IAM_USER>` direct (bootstrap) |

### NGINX Ingress + cert-manager (`helm.tf`)

Shared infrastructure for all platform tools. NGINX routes traffic from the NLB to tool ingresses. cert-manager issues Let's Encrypt certificates via Cloudflare DNS-01 validation.

| Component | Version | Namespace |
|-----------|---------|-----------|
| ingress-nginx | 4.9.0 | `ingress-nginx` |
| cert-manager | v1.14.0 | `cert-manager` |

### Cloudflare DNS (`dns.tf`)

CNAME records pointing platform tool subdomains to the NLB. Each tool adds its own record. Cloudflare proxy is disabled (required for cert-manager DNS01 + Tailscale protocol).

### Headscale VPN (`headscale.tf`)

Self-hosted Tailscale control server with SQLite database and Litestream continuous replication.

**Pod structure**:
```
Headscale Pod
├── initContainers:
│   └── litestream-restore     # Restores DB from S3 (first boot only)
├── containers:
│   └── headscale              # VPN control server
└── sidecars:
    └── litestream             # Continuous WAL replication to S3
```

**Persistence**:
- PVC (`data`): 5Gi gp3 at `/var/lib/headscale` — holds SQLite DB
- ConfigMap (`litestream`): Litestream config at `/etc/litestream.yml`

**Restore logic** (`-if-db-not-exists -if-replica-exists`):

| PVC has DB? | S3 has replica? | Result |
|-------------|-----------------|--------|
| Yes | Yes | Skip (use existing DB) |
| Yes | No | Skip (use existing DB) |
| No | Yes | Restore from S3 |
| No | No | Skip (Headscale creates fresh DB) |

**IRSA**: Service account annotated with IAM role for S3 access. No explicit AWS credentials in the pod.

### Litestream S3 Bucket (`s3.tf`)

Stores WAL replicas for Headscale's SQLite database.

| Setting | Value |
|---------|-------|
| Bucket | `tesslate-platform-litestream` |
| Encryption | AES256 (SSE-S3) |
| Public access | Fully blocked |
| TLS enforcement | Bucket policy denies non-HTTPS |
| Litestream retention | 72h (managed by Litestream) |
| S3 lifecycle | 90 days (safety net for orphaned data) |
| Multipart cleanup | Abort after 1 day |

### IAM Roles (`iam.tf`)

**EKS Deployer Role**: `*-eks-deployer` — role-based cluster access. Users listed in `var.eks_admin_iam_arns` can assume this role to get `AmazonEKSClusterAdminPolicy` cluster admin access via EKS access entries. Same pattern as the aws environment stack (see [EKS Cluster Access Guide](../../guides/eks-cluster-access.md)).

**IRSA roles** for EKS service accounts. Each role is scoped to a specific namespace:serviceaccount pair.

| Role | Service Account | Permissions |
|------|-----------------|-------------|
| `*-eks-deployer` | N/A (IAM role, not IRSA) | EKS cluster admin (assumed by users) |
| `*-vpc-cni` | `kube-system:aws-node` | VPC CNI policy |
| `*-ebs-csi` | `kube-system:ebs-csi-controller-sa` | EBS CSI policy |
| `*-cert-manager` | `cert-manager:cert-manager` | (none — uses Cloudflare, not Route53) |
| `*-headscale` | `headscale:headscale` | S3 Get/Put/Delete/List on litestream bucket |

## Quick Commands

```bash
# Initialize
./scripts/aws-deploy.sh init shared

# Plan changes
./scripts/aws-deploy.sh plan shared

# Apply
./scripts/aws-deploy.sh apply shared

# View outputs
cd k8s/terraform/shared && terraform output

# Configure kubectl for platform cluster
$(terraform -chdir=k8s/terraform/shared output -raw configure_kubectl_command)
```

## Secrets Management

```bash
# Download tfvars from AWS Secrets Manager
./scripts/terraform/secrets.sh download shared

# Upload after editing
./scripts/terraform/secrets.sh upload shared

# View current values
./scripts/terraform/secrets.sh shared
```

## Common Tasks

### Add a New Platform Tool

1. Create `k8s/terraform/shared/<tool>.tf` with Helm release, ingress, and any supporting resources
2. Add a Cloudflare CNAME record in `dns.tf` (or in the tool's own file)
3. Add variables to `variables.tf` and `terraform.tfvars.example`
4. Add outputs to `outputs.tf`
5. Run `./scripts/aws-deploy.sh plan shared` to verify
6. Apply: `./scripts/aws-deploy.sh apply shared`

### Headscale: Create User and Auth Key

```bash
# After deploy, create a user
kubectl exec -n headscale deployment/headscale -- headscale users create dev-team

# Create a reusable auth key (30 days)
kubectl exec -n headscale deployment/headscale -- headscale preauthkeys create \
  --user dev-team --reusable --expiration 720h

# Connect a client
tailscale up --login-server https://headscale.tesslate.com --authkey <KEY>
```

### Verify Litestream Replication

```bash
# Check sidecar logs
kubectl logs -n headscale deployment/headscale -c litestream

# Check init container logs (only relevant on first boot)
kubectl logs -n headscale deployment/headscale -c litestream-restore

# List S3 replicas
aws s3 ls s3://tesslate-platform-litestream/headscale/ --recursive
```

### Recover Headscale DB from S3

If the PVC is lost, delete the pod. The init container will restore from S3 automatically:

```bash
# Delete PVC (triggers fresh restore on next boot)
kubectl delete pvc -n headscale headscale-data
kubectl delete pod -n headscale -l app.kubernetes.io/name=headscale

# Watch restore
kubectl logs -n headscale -l app.kubernetes.io/name=headscale -c litestream-restore -f
```

## Cost Estimate

| Resource | Monthly Cost |
|----------|-------------|
| EKS control plane | $73 |
| NAT Gateway | $32 |
| t3.medium node (1x) | $30 |
| NLB | $16 |
| EBS (gp3, ~10Gi) | $1 |
| S3 (Litestream) | $0.10 |
| ECR (shared images) | $1-5 |
| **Total** | **~$154** |

## Related Documentation

- [Architecture Diagram](../../architecture/diagrams/shared-platform.mmd)
- [ECR Documentation](ecr.md)
- [EKS Documentation](eks.md)
- [AWS Environment Stack](README.md)
- [Infrastructure CLAUDE.md](../CLAUDE.md)
