# Overlay: aws-production

Path: `k8s/overlays/aws-production/`. Builds on `aws-base` with production replicas and tuning.

## Files

| File | Purpose |
|------|---------|
| `kustomization.yaml` | `resources: [../aws-base]`. Image tags pinned to `:production`. Applies the patches below. |
| `env-patch.yaml` | Production env values (domain `opensail.tesslate.com`, log level, feature flags). |
| `replicas-patch.yaml` | Hand-edited production replica counts. |
| `generated-replicas-patch.yaml` | Auto-generated replica patch from capacity-planning tooling. Loaded after `replicas-patch.yaml` so generated values override the hand-edited baseline. |
| `compute/kustomization.yaml` | Deploys the compute pool + Volume Hub + btrfs CSI stack for production. Applied via `./scripts/aws-deploy.sh deploy-compute production`. |

## Deploy

```bash
./scripts/aws-deploy.sh deploy-k8s production
./scripts/aws-deploy.sh deploy-compute production
```

## Context

`kubectl --context=tesslate-production-eks`. Never switch contexts; always pass `--context=` explicitly.
