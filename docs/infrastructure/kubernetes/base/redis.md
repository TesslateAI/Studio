# Base: redis

Kustomize group at `k8s/base/redis/`. Redis used for pub/sub, ARQ queue, caching, and distributed locks.

## Files

| File | Purpose |
|------|---------|
| `kustomization.yaml` | Lists the resources and generates the Redis ConfigMap (`maxmemory 512mb`, `maxmemory-policy volatile-lru`, `appendonly yes`). |
| `redis-deployment.yaml` | Single-replica Redis. Image `redis:7-alpine`. `revisionHistoryLimit: 3`. |
| `redis-service.yaml` | ClusterIP :6379. |
| `redis-pvc.yaml` | 1Gi PVC for AOF persistence. |
| `redis-pdb.yaml` | `PodDisruptionBudget minAvailable: 1`. |

## AWS production

AWS overlays replace this with ElastiCache (`k8s/terraform/aws/elasticache.tf`). The base Deployment is not deployed there; only the Service name (`redis`) is recreated in-cluster to point at the ElastiCache endpoint.
