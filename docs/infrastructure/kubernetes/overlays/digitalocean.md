# Overlay: digitalocean

Path: `k8s/overlays/digitalocean/`. DigitalOcean Kubernetes (DOKS) overlay. Kept for historical / experimental deployments.

## Files

| File | Purpose |
|------|---------|
| `kustomization.yaml` | `resources: [../../base]`. Image registry `registry.digitalocean.com/tesslate-container-registry-nyc3`. |
| `backend-patch.yaml` | Backend patch pointing at DOCR images and DO Spaces-compatible S3 endpoint. |
| `ingress-patch.yaml` | Ingress host + cert-manager annotations for DO's Let's Encrypt flow. |
| `storage-class.yaml` | `tesslate-block-storage` pinned to `do-block-storage`. |
| `secrets/registry-credentials.yaml` | ImagePullSecret for DOCR (gitignored). |

## Status

Lower-priority than AWS. No active CI pipeline. Keep manifests valid so they can be revived if needed.
