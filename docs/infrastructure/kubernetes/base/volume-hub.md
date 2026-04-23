# Base: volume-hub

Kustomize group at `k8s/base/volume-hub/`. Deploys the Volume Hub (storageless gRPC orchestrator) alongside the btrfs CSI stack.

## Files

| File | Purpose |
|------|---------|
| `kustomization.yaml` | Lists the three resources below. |
| `deployment.yaml` | `Deployment tesslate-volume-hub` in `kube-system`. Runs `btrfs-csi-driver --mode=hub`. No PVC, no `SYS_ADMIN`. ServiceAccount `tesslate-volume-hub-sa`. Requests `INTERNAL_API_SECRET` equivalent via `ORCHESTRATOR_INTERNAL_SECRET` (from `tesslate-btrfs-csi-config`). |
| `service.yaml` | `Service tesslate-volume-hub`. ClusterIP exposing port `9750` (Hub gRPC, JSON codec). |
| `rbac.yaml` | ServiceAccount + ClusterRole + ClusterRoleBinding for the Hub. Grants `get`, `list`, `watch` on pods, endpoints, services, nodes so the Hub can resolve the CSI node DaemonSet and track node capacity. |

## Related

- Driver source: [`docs/services/btrfs-csi/pkg/volumehub.md`](../../../services/btrfs-csi/pkg/volumehub.md)
- Storage narrative: [`docs/architecture/storage-architecture.md`](../../../architecture/storage-architecture.md)
- Node side (DaemonSet): `services/btrfs-csi/deploy/manifests/node.yaml` documented in [`docs/services/btrfs-csi/deploy/README.md`](../../../services/btrfs-csi/deploy/README.md)

## Deployment commands

```bash
# Minikube (deploys via compute overlay path)
kubectl apply -k services/btrfs-csi/overlays/minikube --context=tesslate

# AWS
./scripts/aws-deploy.sh deploy-compute production
./scripts/aws-deploy.sh deploy-compute beta
```
