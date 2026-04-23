# Traefik Agent Context

## Purpose

Traefik is the edge proxy for OpenSail's **Docker** deployment mode. Production Kubernetes uses NGINX Ingress instead; do not mix them up.

Traefik's job in Docker mode:

- Route `Host(APP_DOMAIN) && PathPrefix(/api|/ws)` to the orchestrator container (priority 100).
- Route everything else on the same host to the frontend app container (priority 10).
- Route `*.localhost` / `*.<APP_DOMAIN>` subdomains to user project preview containers via Docker provider labels.
- Serve the Traefik dashboard at `/traefik` (basic-auth protected).
- Handle TLS (Let's Encrypt HTTP challenge in dev, Cloudflare DNS challenge in prod).

## Files

| File | Role |
|------|------|
| [traefik/traefik.yml](../../../traefik/traefik.yml) | Static config for local dev: insecure API, HTTP entrypoint, Let's Encrypt HTTP challenge with `admin@tesslate.com`. |
| [traefik/traefik.prod.yml](../../../traefik/traefik.prod.yml) | Static config for prod: secure dashboard, Cloudflare DNS challenge, access log to `/var/log/traefik/access.log`. |
| [traefik/traefik.tunnel.yml](../../../traefik/traefik.tunnel.yml) | Static config for the Cloudflare Tunnel variant: no TLS (Cloudflare handles edge), trusted-IP list for CF header forwarding, JSON access log. |
| [traefik/dynamic/middlewares.yml](../../../traefik/dynamic/middlewares.yml) | `api-strip-prefix` (strip `/api`) and `devcontainer-auth` (forwardAuth to `/api/auth/verify-access`). |
| [traefik/dynamic/routes.yml](../../../traefik/dynamic/routes.yml) | Reference routes. Real routing uses Docker labels in the compose file; this file is kept for docs. |
| [traefik/dynamic/services.yml](../../../traefik/dynamic/services.yml) | Reference services (frontend, backend). Real services come from Docker labels. |

## Patterns

- **Dynamic over static**: the dynamic YAML files are examples. Real routing is defined via Docker labels in the relevant [compose file](../docker-compose/CLAUDE.md).
- **Label contract**: `com.tesslate.routable=true` opts a container in. Without that label Traefik ignores it (enforced by `--providers.docker.constraints=Label('com.tesslate.routable','true')` in the dev entrypoint).
- **Host binding via env**: every router rule uses `Host('${APP_DOMAIN:-localhost}')` so the same compose file works for `localhost` dev, a real domain, and the tunnel variant.
- **ForwardAuth for devcontainers**: the `devcontainer-auth` middleware calls orchestrator's `/api/auth/verify-access` before letting users into preview URLs.

## Related Contexts

- [docs/infrastructure/docker-compose/CLAUDE.md](../docker-compose/CLAUDE.md): where the Docker labels live
- [docs/infrastructure/kubernetes/CLAUDE.md](../kubernetes/CLAUDE.md): the K8s NGINX alternative
- [docs/architecture/deployment-modes.md](../../architecture/deployment-modes.md): when Traefik is used vs NGINX

## When to Load

- Adding a new public route
- Debugging a Docker dev preview URL that 404s
- Rotating TLS / Let's Encrypt / Cloudflare tokens
- Moving a dev stack behind a Cloudflare Tunnel
