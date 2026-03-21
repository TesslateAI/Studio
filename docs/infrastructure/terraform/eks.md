# EKS Cluster Configuration

Amazon EKS cluster setup via Terraform.

**File**: `k8s/terraform/aws/`

## Cluster Configuration

**Name**: `<EKS_CLUSTER_NAME>`
**Version**: 1.28 (configurable via `eks_cluster_version`)
**Region**: us-east-1

### Networking

**VPC**: Created in vpc.tf
**Subnets**: Private subnets (10.0.10.0/24, 10.0.11.0/24)
**Endpoint Access**: Public + Private (for management and internal access)

### IRSA (IAM Roles for Service Accounts)

Enabled via `enable_irsa = true`

Allows pods to assume IAM roles without embedding credentials.

**Example**: Backend pods use IRSA to access S3 without AWS_ACCESS_KEY_ID

## Managed Node Groups

### Primary Node Group

**Name**: `tess-primary`
**Type**: On-demand EC2 instances
**Instance Types**: `["t3.large"]` (configurable)

**Scaling**:
- Min: 1 node
- Max: 10 nodes
- Desired: 2 nodes

**Disk**: 50GB gp3 (per node)

**AZ Pinning**: Node groups can be pinned to specific availability zones via `eks_node_azs` variable. This ensures EBS volumes and nodes are co-located in the same AZ, preventing cross-AZ volume attachment failures.

**Labels**:
- `role=primary`
- `environment=production`

**Use Case**: Platform services (backend, frontend, postgres)

### Spot Node Group (Optional)

**Name**: `tess-spot`
**Type**: Spot instances (90% cost savings)
**Instance Types**: `["t3.large", "t3.xlarge", "t3a.large", "t3a.xlarge"]`

**Scaling**:
- Min: 0 nodes
- Max: 10 nodes
- Desired: 1 node

**Taints**:
- `tesslate.io/spot=true:PREFER_NO_SCHEDULE`

**Labels**:
- `tesslate.io/workload-type=user-project`

**Use Case**: User dev containers (can tolerate interruptions)

## Cluster Add-ons

### CoreDNS

DNS resolution for pods
- Version: Explicitly configured in Terraform (addon resource)
- Replicas: 2

### kube-proxy

Network proxy for Services
- Version: Explicitly configured in Terraform (addon resource)

### VPC CNI

AWS pod networking
- Version: Latest
- IRSA: Enabled
- IP prefix delegation: Enabled (more IPs per node)

### EBS CSI Driver

Persistent volume provisioning (used for platform PVCs and as a dependency for EBS VolumeSnapshots)
- Version: Latest
- IRSA: Enabled
- Provisioner: `ebs.csi.aws.com`

### CSI Snapshot Controller

Required for EBS CSI driver to create/restore VolumeSnapshots. Installed via Helm.
- **Chart**: `snapshot-controller` (from `https://piraeus.io/helm-charts`)
- **Version**: 3.0.6
- **Namespace**: `kube-system`
- **Defined in**: `k8s/terraform/aws/helm.tf`

## Storage

### Storage Classes

#### `tesslate-block-storage` (EBS gp3)

**Use case**: Platform PVCs (PostgreSQL, Redis, LiteLLM) and legacy fallback
**Provisioner**: `ebs.csi.aws.com`
**Access Mode**: ReadWriteOnce
**Reclaim Policy**: Delete
**Volume Binding**: WaitForFirstConsumer (provisions on first use)
**Encryption**: Enabled
**Defined in**: `k8s/terraform/aws/eks.tf` (`kubernetes_storage_class.gp3`)

**Parameters**:
```hcl
type      = "gp3"
fsType    = "ext4"
encrypted = "true"
```

#### `tesslate-btrfs` (btrfs CSI — primary for user projects)

**Use case**: User project volumes and template builds. The btrfs CSI driver is the primary storage driver for user workloads, providing instant snapshot-clone for project creation from pre-built templates.

The btrfs CSI driver itself is **not** managed by Terraform — it is deployed via Kustomize manifests. Terraform manages the supporting infrastructure:
- IRSA role for S3 access (see below)
- ServiceAccount with IRSA annotation (`tesslate-btrfs-csi-node` in `kube-system`)
- Config secret with S3 bucket and rclone settings
- ECR repository for the driver image (in the shared stack)
- S3 bucket for snapshot persistence

### btrfs CSI Snapshot S3 Bucket

**Defined in**: `k8s/terraform/aws/s3.tf` (`aws_s3_bucket.btrfs_snapshots`)

Stores btrfs send/receive streams (zstd-compressed) for volume persistence. The CSI sync daemon uploads snapshots here; cross-node restores download them.

**Bucket name**: `{project_name}-btrfs-snapshots-{environment}-{suffix}`
**Versioning**: Enabled
**Encryption**: AES256 (SSE-S3, bucket key enabled)
**Public access**: Fully blocked
**TLS**: Enforced via bucket policy

**Lifecycle rules**:
- Non-current versions transition to STANDARD_IA after 30 days
- Non-current versions transition to GLACIER after 90 days
- Non-current versions expire after 365 days
- Incomplete multipart uploads aborted after 7 days

### VolumeSnapshotClass (EBS)

**Name**: `tesslate-ebs-snapshots`
**Driver**: `ebs.csi.aws.com`
**Deletion Policy**: Retain (snapshots persist when VolumeSnapshotContent is deleted, enabling soft-delete recovery)
**Defined in**: `k8s/terraform/aws/eks.tf` (`kubectl_manifest.ebs_snapshot_class`)
**Depends on**: CSI Snapshot Controller Helm release

### Volume Hub

The Volume Hub is a storageless orchestrator that provides S3 gateway and cache orchestration for volumes.

Terraform manages the IRSA role and ServiceAccount — the Volume Hub workload itself is deployed via Kustomize.

**ServiceAccount**: `tesslate-volume-hub` (in `kube-system`)
**IRSA Role**: `{cluster_name}-volume-hub`
**Permissions**: Same S3 policy as btrfs CSI driver (read/write to btrfs snapshots bucket)
**Defined in**: `k8s/terraform/aws/iam.tf` (IRSA), `k8s/terraform/aws/kubernetes.tf` (ServiceAccount)

## Security Groups

### Node Security Group

**Ingress**:
- All traffic from VPC CIDR (10.0.0.0/16)
- Required for pod-to-pod communication across nodes

**Egress**:
- All traffic (0.0.0.0/0)
- Required for internet access (npm, pip, API calls)

### Cluster Security Group

Managed by EKS module, allows:
- Control plane → nodes (443, 10250)
- Nodes → control plane (443)

## Cluster Access (eks-deployer Role)

EKS cluster access is managed via a dedicated `eks-deployer` IAM role with EKS access policy rather than direct IAM user access entries. Users listed in `eks_admin_iam_arns` (in each environment's tfvars) can assume this role to get cluster admin access.

**Role**: `tesslate-{env}-eks-eks-deployer`
**Access Policy**: `AmazonEKSClusterAdminPolicy` (full cluster admin)
**Trust Policy**: Allows `sts:AssumeRole` from ARNs in `var.eks_admin_iam_arns`

The `aws-deploy.sh` script automatically assumes this role for all cluster operations (`deploy-k8s`, `build`, `reload`).

**Full guide**: [EKS Cluster Access Guide](../../guides/eks-cluster-access.md)

**Note**: The same `eks-deployer` pattern is used in both the per-environment stack (`k8s/terraform/aws/`) and the shared platform stack (`k8s/terraform/shared/`).

## IRSA Roles

### VPC CNI Role

**Purpose**: Manage ENIs for pod networking
**Service Account**: `aws-node` (kube-system namespace)
**Permissions**: VPC CNI policy (attach/detach ENIs)

### EBS CSI Driver Role

**Purpose**: Provision EBS volumes and manage EBS snapshots
**Service Account**: `ebs-csi-controller-sa` (kube-system namespace)
**Permissions**: EBS CSI policy (create/attach/delete volumes) + EBS snapshot policy (CreateSnapshot, DeleteSnapshot, DescribeSnapshots, DescribeVolumes, CreateTags)

### btrfs CSI Driver Role

**Purpose**: Sync/restore btrfs volume snapshots to/from S3
**Service Account**: `tesslate-btrfs-csi-node` (kube-system namespace)
**Role Name**: `{cluster_name}-btrfs-csi`
**Permissions**: S3 read/write to the btrfs snapshots bucket (GetObject, PutObject, DeleteObject, ListBucket, multipart upload)
**Defined in**: `k8s/terraform/aws/iam.tf` (`module.btrfs_csi_irsa`)

### Volume Hub Role

**Purpose**: S3 access for volume manifest storage and cache orchestration
**Service Account**: `tesslate-volume-hub` (kube-system namespace)
**Role Name**: `{cluster_name}-volume-hub`
**Permissions**: Same S3 policy as btrfs CSI driver (shared `btrfs_csi_s3_access` policy)
**Defined in**: `k8s/terraform/aws/iam.tf` (`module.volume_hub_irsa`)

### Backend Service Account Role

**Purpose**: S3 access for project storage
**Service Account**: `tesslate-backend-sa` (tesslate namespace)
**Permissions**: Read/write to project bucket

## Cluster Autoscaler

**Future Enhancement**: Install via Helm

Tags required for autoscaler:
```hcl
tags = {
  "k8s.io/cluster-autoscaler/enabled" = "true"
  "k8s.io/cluster-autoscaler/${cluster_name}" = "owned"
}
```

Already applied to node groups.

## Upgrades

### Control Plane Upgrade

1. Update `eks_cluster_version` in terraform.tfvars
2. Run `terraform apply`
3. Control plane upgrades automatically (15-20 min)

### Node Group Upgrade

**Option 1**: In-place (risky)
- Terraform replaces nodes one by one
- May cause downtime if pods not properly configured

**Option 2**: Blue/Green (recommended)
1. Create new node group with new version
2. Cordon old nodes: `kubectl cordon {node-name}`
3. Drain old nodes: `kubectl drain {node-name} --ignore-daemonsets`
4. Delete old node group in Terraform

### Add-on Upgrades

Managed by AWS, auto-upgrade to latest compatible version.

Manual upgrade:
```bash
aws eks update-addon --cluster-name <EKS_CLUSTER_NAME> --addon-name vpc-cni --resolve-conflicts OVERWRITE
```

## Monitoring

### Cluster Status

```bash
aws eks describe-cluster --name <EKS_CLUSTER_NAME> --query "cluster.status"
```

### Node Health

```bash
kubectl get nodes
kubectl describe node {node-name}
```

### Add-on Status

```bash
aws eks list-addons --cluster-name <EKS_CLUSTER_NAME>
aws eks describe-addon --cluster-name <EKS_CLUSTER_NAME> --addon-name vpc-cni
```

## Troubleshooting

### Node Not Ready

```bash
kubectl describe node {node-name}
# Check events for errors

# SSH to node (via Systems Manager)
aws ssm start-session --target {instance-id}
```

### Pod Networking Issues

```bash
# Check VPC CNI pods
kubectl get pods -n kube-system -l k8s-app=aws-node

# View VPC CNI logs
kubectl logs -n kube-system -l k8s-app=aws-node --tail=50
```

### Storage Issues

```bash
# Check EBS CSI driver
kubectl get pods -n kube-system -l app.kubernetes.io/name=aws-ebs-csi-driver

# View EBS CSI driver logs
kubectl logs -n kube-system -l app=ebs-csi-controller --tail=50

# Check btrfs CSI driver pods
kubectl get pods -n kube-system -l app=tesslate-btrfs-csi-node

# View btrfs CSI driver logs
kubectl logs -n kube-system -l app=tesslate-btrfs-csi-node --tail=50

# Check Volume Hub
kubectl get pods -n kube-system -l app.kubernetes.io/name=tesslate-volume-hub

# View Volume Hub logs
kubectl logs -n kube-system -l app.kubernetes.io/name=tesslate-volume-hub --tail=50

# Check PVCs
kubectl get pvc --all-namespaces
kubectl describe pvc {pvc-name} -n {namespace}

# Check btrfs CSI config secret
kubectl get secret -n kube-system tesslate-btrfs-csi-config -o yaml
```

## Cost Optimization

1. **Use Spot for dev containers**: 90% savings
2. **Enable autoscaling**: Scale down during off-hours
3. **Right-size instances**: Use t3.medium instead of t3.large if sufficient
4. **Use gp3 instead of gp2**: 20% cheaper
5. **Set resource requests/limits**: Prevent over-provisioning

## Related Documentation

- [README.md](README.md): Terraform overview
- [ecr.md](ecr.md): Container registry
- [s3.md](s3.md): Project storage
- AWS EKS: https://docs.aws.amazon.com/eks/
