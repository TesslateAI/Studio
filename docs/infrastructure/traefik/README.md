# Traefik (Docker mode only)

> Local dev and non-K8s production routing. Kubernetes production uses NGINX Ingress instead.

## Variants

| File | Use it when | Entrypoints | TLS |
|------|-------------|-------------|-----|
| [traefik/traefik.yml](../../../traefik/traefik.yml) | Local dev via [docker-compose.yml](../../../docker-compose.yml) | `:80`, `:443` | Let's Encrypt HTTP challenge |
| [traefik/traefik.prod.yml](../../../traefik/traefik.prod.yml) | Self-hosted production via [docker-compose.prod.yml](../../../docker-compose.prod.yml) | `:80`, `:443` | Let's Encrypt DNS challenge via Cloudflare |
| [traefik/traefik.tunnel.yml](../../../traefik/traefik.tunnel.yml) | Behind a Cloudflare Tunnel via [docker-compose.cloudflare-tunnel.yml](../../../docker-compose.cloudflare-tunnel.yml) | `:80` only, bound to `127.0.0.1:8080` | None (CF terminates at the edge) |

All three enable:

- `providers.docker` with `exposedByDefault: false` so containers opt in via labels.
- `providers.file` with `directory: /etc/traefik/dynamic` so the YAML below is hot-reloaded.

## Dynamic configuration

| File | What it declares |
|------|------------------|
| [traefik/dynamic/middlewares.yml](../../../traefik/dynamic/middlewares.yml) | `api-strip-prefix` strips `/api`. `devcontainer-auth` does forwardAuth against `http://tesslate-orchestrator:8000/api/auth/verify-access` to gate preview URLs. Trusts Traefik's forward headers. |
| [traefik/dynamic/routes.yml](../../../traefik/dynamic/routes.yml) | Reference-only. Real routing lives on compose labels. |
| [traefik/dynamic/services.yml](../../../traefik/dynamic/services.yml) | Reference-only named services (`frontend`, `backend`). |

## Routing model (compose labels)

The dev compose file wires every service via labels. Highlights:

| Container | Key labels |
|-----------|------------|
| `tesslate-traefik` | Dashboard at `/traefik`, basic-auth via `TRAEFIK_BASIC_AUTH`, TLS via `letsencrypt` resolver. |
| `tesslate-orchestrator` | `com.tesslate.routable=true`; catches `/api` and `/ws`; priority 100; injects `X-Forwarded-Proto`. |
| `tesslate-app` | `com.tesslate.routable=true`; catches everything else except `/api`, `/ws`, `/preview`, `/traefik`; priority 10. |
| User project containers | Registered dynamically with the same `com.tesslate.routable` label plus a subdomain rule. |

## Dashboard

- Dev: `http://${APP_DOMAIN}/traefik` with basic-auth (default user `admin`, password set via `TRAEFIK_BASIC_AUTH`).
- Prod: same URL, HTTPS only, still basic-auth gated.
- Tunnel: exposed locally at `127.0.0.1:8081`.

## TLS

- **Dev** (`traefik.yml`): HTTP challenge, storage in `acme.json`.
- **Prod** (`traefik.prod.yml`): DNS challenge using Cloudflare, resolvers `1.1.1.1`, `8.8.8.8`, storage in `/etc/traefik/acme.json`, requires `CLOUDFLARE_DNS_API_TOKEN` in the environment.
- **Tunnel** (`traefik.tunnel.yml`): no TLS; trusts CF IPs for `forwardedHeaders.trustedIPs`.

## Related

- Docker Compose overview: [docs/infrastructure/docker-compose/README.md](../docker-compose/README.md)
- Deployment modes: [docs/architecture/deployment-modes.md](../../architecture/deployment-modes.md)
- K8s alternative: [docs/infrastructure/kubernetes/README.md](../kubernetes/README.md)
