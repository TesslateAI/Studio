# Overlay: gke

Path: `k8s/overlays/gke/`. Google Kubernetes Engine overlay. Experimental; not in active production.

## Files

| File | Purpose |
|------|---------|
| `kustomization.yaml` | `resources: [../../base]`. Image registry under `gcr.io` / Artifact Registry. |
| `backend-patch.yaml` | Backend patch for GKE env: GCS credentials via workload identity, Cloud SQL proxy sidecar option. |
| `ingress-patch.yaml` | GKE-native Ingress annotations (ManagedCertificate). |
| `storage-class.yaml` | Pinned to `standard-rwo` (GCE PD). |

## Status

Reserved for future deployments. Useful as a reference when porting OpenSail to a new cloud: patches mirror the AWS overlay structure (image override, ingress host, storage class).
