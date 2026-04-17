# crm-with-postgres

End-to-end verification seed for the Tesslate Apps platform. Demonstrates:

- **Multi-container app**: Next.js `web` (primary UI surface) + Node `api` + Postgres `db` service container.
- **CSI-backed persistent volume**: `db` mounts `/var/lib/postgresql/data` on the per-install volume so Postgres state survives restarts.
- **Secrets**: `db` reads `POSTGRES_PASSWORD` from a Kubernetes secret via `${secret:pg-creds/password}`.
- **env_injection ContainerConnection**: `db -> api` injects `DATABASE_URL` into the API pod, resolved from the connection's `config.env_mapping`.
- **Manifest schema 2025-02**.

## Required cluster secret

Before the app starts, create a `pg-creds` secret in the project namespace with a `password` key. The installer does not auto-create declared secrets today — set it via the per-container "encrypted secrets" UI/PATCH endpoint, or directly:

```
kubectl --context=tesslate -n proj-<uuid> create secret generic pg-creds \
  --from-literal=password='<choose-a-password>'
```

## Install on minikube

```
kubectl --context=tesslate -n tesslate exec deploy/tesslate-backend -- \
  python -m scripts.seed_crm_with_postgres_app
```

Then visit `/apps` in Studio, install, and start the project.
