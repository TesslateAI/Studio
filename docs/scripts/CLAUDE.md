# Scripts Agent Context

## Purpose

The `scripts/` directory houses operational helpers for OpenSail: local dev setup, deployment, seeds, migrations, LiteLLM user management, one-off diagnostics, and codebase analysis. This context tells an AI agent where to look when the user asks "run the seed", "bump budgets", "deploy to AWS", etc.

## Layout

| Subdir | Purpose |
|--------|---------|
| (root) | Cross-cutting helpers: analyzer, installer, docker/minikube/aws CLIs, admin tooling, e2e tests |
| `deployment/` | Local dev bring-up (bash + Windows batch/PowerShell), dev-server image builder |
| `kubernetes/` | `manage-k8s.sh` lifecycle and `cleanup-k8s.sh` destroy helpers |
| `litellm/` | LiteLLM team, virtual key, model update, and migration scripts |
| `migration/unified-snapshots/` | One-shot production migration from linear layer CAS to unified snapshot DAG |
| `migrations/` | Standalone ALTER-TABLE style column additions (prefer Alembic for new work) |
| `seed/` | Thin wrappers around `orchestrator/app/seeds/*`, plus activity simulation |
| `terraform/` | `secrets.sh`: tfvars up/down to AWS Secrets Manager |
| `utilities/` | Misc health checks and user admin helpers |

Canonical seed logic lives in `orchestrator/app/seeds/`. The wrappers in `scripts/seed/` exist so you can run a single seed by name without importing the whole app package tree.

## Related Contexts

- [docs/scripts/README.md](README.md): file-by-file reference
- [docs/infrastructure/kubernetes/CLAUDE.md](../infrastructure/kubernetes/CLAUDE.md): where `manage-k8s.sh` plugs in
- [docs/infrastructure/docker-compose/CLAUDE.md](../infrastructure/docker-compose/CLAUDE.md): what `docker.sh` wraps
- [docs/orchestrator/services/CLAUDE.md](../orchestrator/services/CLAUDE.md): canonical seed implementations

## When to Load

- User asks how to seed, migrate, or reset data
- User wants to run a one-off admin task (promote admin, regenerate LiteLLM keys)
- Debugging a script the CI invokes
- Writing a new helper (pattern-match against an existing one)

## Non-Goals

Application code does not import from `scripts/`. Anything meant to run inside the orchestrator or worker lives under `orchestrator/app/`.
