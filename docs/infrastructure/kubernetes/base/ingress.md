# Base: ingress

Kustomize group at `k8s/base/ingress/`. NGINX Ingress rules for the platform.

## File

| File | Purpose |
|------|---------|
| `main-ingress.yaml` | Routes `/` -> `tesslate-frontend-service:80`, `/api/*` -> `tesslate-backend-service:8000`. Overlays patch the host. Annotations set proxy-body-size `50m`, proxy-read-timeout `3600` (for WS), `use-regex: true`, and a `server-snippet` that returns 403 for `/api/internal/*` before it reaches the backend. |

## Security: `/api/internal/*`

The server snippet blocks internal endpoints at the edge (Layer 1). Layer 2 is the backend shared-secret middleware (`INTERNAL_API_SECRET`). Layer 3 is the IMDS egress block on user namespaces. See `docs/infrastructure/kubernetes/CLAUDE.md` "Network Boundary Security" for the full runbook.

## TLS

Overlays wire TLS: AWS overlays set `tls.secretName: tesslate-wildcard-tls` (cert-manager managed); minikube leaves TLS disabled.
