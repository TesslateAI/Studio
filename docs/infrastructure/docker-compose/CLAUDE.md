# Docker Compose Agent Context

## Purpose

OpenSail ships four Docker Compose files at the repo root. Each has a single job. Load this context when the user wants to know which one to bring up, what env vars they need, or why a service looks different across files.

| File | Intended mode | Loads Traefik | Domain handling |
|------|---------------|---------------|-----------------|
| [docker-compose.yml](../../../docker-compose.yml) | Local dev (default) | Yes (dev variant) | `APP_DOMAIN=localhost` by default |
| [docker-compose.prod.yml](../../../docker-compose.prod.yml) | Self-hosted production | Yes (prod variant) | `APP_DOMAIN=<real domain>` |
| [docker-compose.cloudflare-tunnel.yml](../../../docker-compose.cloudflare-tunnel.yml) | Production behind Cloudflare Tunnel | Yes (tunnel variant, bound to `127.0.0.1`) | Domain is whatever CF routes to the tunnel |
| [docker-compose.test.yml](../../../docker-compose.test.yml) | Integration tests | No | Stands up an isolated Postgres only |

## Invariants

- `DEPLOYMENT_MODE=docker` in every orchestrator env block. This selects the Docker orchestrator in `app/services/orchestration/factory.py`.
- Every user-facing container gets `com.tesslate.routable=true` so Traefik picks it up.
- The orchestrator mounts `/var/run/docker.sock` so it can start user project containers.
- `tesslate-projects-data` is a named volume shared by the orchestrator, worker, and all user project containers: one volume, one set of files.

## Related Contexts

- [docs/infrastructure/traefik/CLAUDE.md](../traefik/CLAUDE.md): routing and TLS details
- [docs/infrastructure/docker/CLAUDE.md](../docker/CLAUDE.md): Dockerfiles, build details, symlink fix
- [docs/architecture/deployment-modes.md](../../architecture/deployment-modes.md): where Docker fits vs K8s and Desktop

## When to Load

- Bringing up a dev stack
- Debugging a compose service
- Adding a new service or volume
- Cloning prod config to a new environment
