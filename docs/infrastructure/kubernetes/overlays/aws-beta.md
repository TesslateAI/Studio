# Overlay: aws-beta

Path: `k8s/overlays/aws-beta/`. Builds on `aws-base` with beta-specific replicas and env values.

## Files

| File | Purpose |
|------|---------|
| `kustomization.yaml` | `resources: [../aws-base]`. Image tags pinned to `:beta`. Applies the patches below. |
| `env-patch.yaml` | Sets beta-only env values (e.g. `APP_DOMAIN`, `CORS_ORIGINS`). |
| `replicas-patch.yaml` | Lower replica counts for cost-sensitive beta. |
| `compute/kustomization.yaml` | Sub-overlay that deploys the compute pool + Volume Hub + btrfs CSI stack for beta. Applied via `./scripts/aws-deploy.sh deploy-compute beta`. |

## Deploy

```bash
./scripts/aws-deploy.sh deploy-k8s beta
./scripts/aws-deploy.sh deploy-compute beta
```

## Context

`kubectl --context=tesslate-beta-eks`. See `docs/infrastructure/kubernetes/CLAUDE.md` "kubectl Context Safety".
