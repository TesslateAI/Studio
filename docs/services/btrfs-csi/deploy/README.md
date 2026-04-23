# btrfs-csi deploy manifests

Kustomize base for the btrfs CSI driver, Volume Hub, storage classes, snapshot class, and related infra. Lives at `services/btrfs-csi/deploy/`.

## Files

| File | Purpose |
|------|---------|
| `kustomization.yaml` | Root kustomization: lists every manifest below and applies common labels. |
| `manifests/csi-driver.yaml` | `CSIDriver` registration for `btrfs.csi.tesslate.io`. Sets `podInfoOnMount`, `attachRequired: false`, fsGroup policy. |
| `manifests/node.yaml` | `DaemonSet tesslate-btrfs-csi-node`. Runs `--mode=node`, starts NodeOps :9741, FileOps :9742, Drain :9743, sync daemon, GC. Privileged, `SYS_ADMIN`, mounts `/mnt/tesslate-pool-data` and host `/dev`. Init container `init-btrfs-pool` creates the sparse loopback image. preStop hook drains via `POST /drain`. |
| `manifests/node-service.yaml` | `Service tesslate-btrfs-csi-node-svc` (headless, `ClusterIP: None`). Exposes NodeOps and FileOps ports. Hub discovers node pods via Endpoints on this Service. |
| `manifests/storage-class.yaml` | `StorageClass tesslate-btrfs` + template-specific classes (`tesslate-btrfs-nextjs`, etc). `volumeBindingMode: WaitForFirstConsumer`. |
| `manifests/snapshot-class.yaml` | `VolumeSnapshotClass tesslate-btrfs-snapshots`. Uses `btrfs.csi.tesslate.io`, `deletionPolicy: Delete`. |
| `manifests/config-secret.yaml` | Template `Secret csi-credentials`. Holds `STORAGE_PROVIDER`, `STORAGE_BUCKET`, rclone config, NodeOps / FileOps TLS material. Overlays supply real values. |
| `manifests/image-precache.yaml` | `DaemonSet` that pulls the CSI image so it is always warm on every node; avoids pull storms during driver upgrades. |
| `manifests/network-policy.yaml` | Restricts NodeOps and FileOps ingress to the `tesslate` namespace (orchestrator) and to the Hub pod. Drain HTTP is restricted to same-node kubelet. |
| `manifests/pdb.yaml` | `PodDisruptionBudget` for the Hub Deployment (`minAvailable: 1`). |
| `rbac/node-rbac.yaml` | `ServiceAccount` + `ClusterRole` + `ClusterRoleBinding` granting the node DaemonSet access to nodes, pods (read), events, and the CSI lease leases. |

## Overlays

| Overlay | Path | Purpose |
|---------|------|---------|
| `overlays/minikube/kustomization.yaml` | `services/btrfs-csi/overlays/minikube/` | Local dev overlay. |
| `overlays/minikube/service-accounts.yaml` | Minikube-scoped SAs (Hub + node). |
| `overlays/minikube/sa-and-config.yaml` | Overrides `csi-credentials` with MinIO values + local bucket. |
| `overlays/minikube/csi-credentials.yaml` | Actual MinIO creds (gitignored in prod). |
| `overlays/minikube/csi-credentials.example.yaml` | Template for the above. |

Apply from the root `k8s/` overlay, which references this base under `services/btrfs-csi/overlays/minikube` for local dev and `services/btrfs-csi/deploy` directly for cloud.

## Ports opened

| Port | Service |
|------|---------|
| 9741/TCP | NodeOps gRPC |
| 9742/TCP | FileOps gRPC |
| 9743/TCP | Drain HTTP (localhost only) |
| 9750/TCP | Hub gRPC (Deployment only) |
| 9080/TCP | Prometheus metrics |
