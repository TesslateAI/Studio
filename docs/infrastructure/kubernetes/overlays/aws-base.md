# Overlay: aws-base

Path: `k8s/overlays/aws-base/`. Shared patches consumed by both `aws-beta` and `aws-production`.

## Files

| File | Purpose |
|------|---------|
| `kustomization.yaml` | `resources: [../../base]`. Applies the patches below and pins the image names to ECR URLs (account `<AWS_ACCOUNT_ID>`, region `us-east-1`). |
| `backend-patch.yaml` | Strategic-merge patch on `tesslate-backend`. Uses `envFrom` to auto-mount `tesslate-app-secrets`, `postgres-secret`, `s3-credentials`. Uses `env` with `$patch: replace` to set static values (class names, feature flags) and alias `K8S_INGRESS_DOMAIN -> APP_DOMAIN`. See `docs/infrastructure/CLAUDE.md` "AWS Overlay: envFrom Auto-Sync". |
| `frontend-patch.yaml` | Points frontend image at ECR. Sets `imagePullPolicy: Always`. |
| `worker-patch.yaml` | ARQ worker patch. Same image as backend. Higher concurrency limits. `revisionHistoryLimit: 3`. |
| `storage-class.yaml` | Ensures `tesslate-block-storage` EBS gp3 storage class exists. Superseded in practice by Terraform-managed storage classes; kept for kustomize build cleanliness. |

## envFrom + $patch: replace contract

- Terraform (`k8s/terraform/aws/kubernetes.tf`) creates three secrets. Any key added there becomes a backend env var automatically.
- `env` entries with `$patch: replace` replace the base manifest array entirely, preventing stale base entries (old image tags, old domain) from merging in.
- Static class names live in the patch; secret-based values live in Terraform.

## Related

- `aws-beta.md`, `aws-production.md` for environment-specific overlays.
- `docs/infrastructure/terraform/README.md` for the backing Terraform stack.
