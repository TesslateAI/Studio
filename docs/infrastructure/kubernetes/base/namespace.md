# Base: namespace

Kustomize group at `k8s/base/namespace/`.

## File

| File | Purpose |
|------|---------|
| `tesslate.yaml` | `Namespace tesslate`. Labels: `app.kubernetes.io/name: tesslate-studio`, `app.kubernetes.io/managed-by: kustomize`. All platform resources deploy here by default. |

## Neighbour namespaces

| Namespace | Source | Purpose |
|-----------|--------|---------|
| `tesslate-compute-pool` | `k8s/base/compute-pool/namespace.yaml` | Ephemeral compute pods. |
| `kube-system` | cluster-provided | Hosts `tesslate-volume-hub`, CSI DaemonSet. |
| `ingress-nginx` | Helm chart (shared stack) | NGINX Ingress controller. |
| `cert-manager` | Helm chart (shared stack) | TLS certificates (AWS only). |
| `minio-system` | `k8s/overlays/minikube/minio/` | Local MinIO (minikube only). |
| `cloudflare-tunnel` | `k8s/overlays/minikube/cloudflare-tunnel/` | Tunnel pod (minikube only). |
| `proj-{uuid}` | created by orchestrator at project start | One per user project. |
