# Base: core

Kustomize group at `k8s/base/core/`. Platform-level workloads in the `tesslate` namespace.

## Files

| File | Purpose |
|------|---------|
| `backend-deployment.yaml` | FastAPI orchestrator (`tesslate-backend`). Port 8000. ServiceAccount `tesslate-backend-sa`. `revisionHistoryLimit: 3`. |
| `backend-service.yaml` | `Service tesslate-backend-service` ClusterIP :8000. |
| `frontend-deployment.yaml` | React UI via NGINX. Port 80. `revisionHistoryLimit: 3`. |
| `frontend-service.yaml` | `Service tesslate-frontend-service` ClusterIP :80. |
| `worker-deployment.yaml` | ARQ worker running `arq orchestrator.app.worker.WorkerSettings`. Shares backend image and secrets. `revisionHistoryLimit: 3`. |
| `gateway-deployment.yaml` | Gateway process for messaging channels. Deployment strategy `Recreate`, `replicas: 1` for single-writer semantics. |
| `namespace-reaper-cronjob.yaml` | `*/2 * * * *` cronjob that hibernates idle `proj-*` namespaces (S3 Sandwich / Volume Hub triggerSync). Uses `envFrom.secretRef`. |
| `snapshot-cleanup-cronjob.yaml` | Daily cronjob that deletes expired soft-deleted K8s VolumeSnapshots (`snapshot_manager.py` integration). |
| `priority-classes.yaml` | `PriorityClass` definitions: platform-critical (high), compute-ephemeral (low). Used by scheduling to evict ephemeral pods first under pressure. |

## Related

- [`namespace.md`](namespace.md) for the `tesslate` Namespace resource.
- [`database.md`](database.md) for PostgreSQL workloads.
- [`redis.md`](redis.md) for Redis.
- [`security.md`](security.md) for RBAC + NetworkPolicies + quotas.
- [`ingress.md`](ingress.md) for the main-ingress file.
