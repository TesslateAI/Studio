# crm-with-postgres

End-to-end verification seed for the Tesslate Apps platform. Demonstrates:

- **Multi-container app**: Next.js `web` (primary UI surface) + Node `api` + Postgres `db` service container.
- **CSI-backed persistent volume**: `db` mounts `/var/lib/postgresql/data` on the per-install volume so Postgres state survives restarts.
- **Secrets**: `db` reads `POSTGRES_PASSWORD` from a Kubernetes secret via `${secret:pg-creds/password}`.
- **env_injection ContainerConnection**: `db -> api` injects `DATABASE_URL` into the API pod, resolved from the connection's `config.env_mapping`.
- **Manifest schema 2025-02**.

## Per-install `pg-creds` secret

`db` references `${secret:pg-creds/password}` and the connector's
`DATABASE_URL` template references the same secret. The orchestrator's
per-install secret materializer auto-creates `pg-creds` in the project
namespace at first `/start` with a random `password` value, so no manual
step is required.

To override the generated value (e.g. to point Postgres at an existing
password), delete the auto-created Secret and re-create it before
starting the app:

```
kubectl --context=tesslate -n proj-<uuid> delete secret pg-creds
kubectl --context=tesslate -n proj-<uuid> create secret generic pg-creds \
  --from-literal=password='<choose-a-password>'
```

Subsequent restarts reuse the Secret you put there.

## Install on minikube

```
kubectl --context=tesslate -n tesslate exec deploy/tesslate-backend -- \
  python -m scripts.seed_crm_with_postgres_app
```

Then visit `/apps` in Studio, install, and start the project.
