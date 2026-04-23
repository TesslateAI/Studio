# Base: database

Kustomize group at `k8s/base/database/`. Platform PostgreSQL.

## Files

| File | Purpose |
|------|---------|
| `postgres-deployment.yaml` | `Deployment postgres`. Image `postgres:15-alpine`. Port 5432. Mounts `postgres-pvc` on `/var/lib/postgresql/data`. `revisionHistoryLimit: 3`. |
| `postgres-service.yaml` | ClusterIP `postgres` :5432. |
| `postgres-pvc.yaml` | 10Gi PVC from the default storage class. |
| `postgres-pdb.yaml` | `PodDisruptionBudget` with `minAvailable: 1` so voluntary drains cannot take down the database. |

## Credentials

`postgres-secret` (provided by overlays) holds `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`. The backend reads `DATABASE_URL` built from these.

## AWS production

In AWS the cluster-local Postgres Deployment is replaced at overlay time by an RDS instance declared in `k8s/terraform/aws/kubernetes.tf`. The Service and Secret are still present in-cluster so downstream code sees a stable DNS name.
