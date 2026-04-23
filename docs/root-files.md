# Repo Root Files

> Every file at the repository root, what it is, and which doc owns it.

## Entrypoint docs

| File | Purpose |
|------|---------|
| [/home/smirk/Tesslate-Studio/README.md](../README.md) | Public-facing project README (OpenSail overview, quickstart, capabilities). |
| [/home/smirk/Tesslate-Studio/CONTRIBUTING.md](../CONTRIBUTING.md) | Contribution guide (branch model, commit conventions, review process). |
| [/home/smirk/Tesslate-Studio/TESTING.md](../TESTING.md) | How to run the test suites (unit, integration, e2e). |
| [/home/smirk/Tesslate-Studio/THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md) | Licenses and notices for third-party software OpenSail depends on. |
| [/home/smirk/Tesslate-Studio/LICENSE](../LICENSE) | OpenSail is Apache 2.0. |
| [/home/smirk/Tesslate-Studio/NOTICE](../NOTICE) | Apache 2.0 NOTICE file. |
| [/home/smirk/Tesslate-Studio/design_rules.md](../design_rules.md) | Canonical design system reference (typography, color, spacing). See also the `frontend-design` skill. |
| [/home/smirk/Tesslate-Studio/AGENTS.md](../AGENTS.md) | Short note for coding agents (non-normative; defers to [root CLAUDE.md](../CLAUDE.md)). |
| [/home/smirk/Tesslate-Studio/CLAUDE.md](../CLAUDE.md) | Root agent context; this is the source of truth for Claude Code sessions. |

## Compose files

See [docs/infrastructure/docker-compose/README.md](infrastructure/docker-compose/README.md) for full details.

| File | Mode |
|------|------|
| [/home/smirk/Tesslate-Studio/docker-compose.yml](../docker-compose.yml) | Local dev |
| [/home/smirk/Tesslate-Studio/docker-compose.prod.yml](../docker-compose.prod.yml) | Self-hosted production |
| [/home/smirk/Tesslate-Studio/docker-compose.cloudflare-tunnel.yml](../docker-compose.cloudflare-tunnel.yml) | Production behind a Cloudflare Tunnel |
| [/home/smirk/Tesslate-Studio/docker-compose.test.yml](../docker-compose.test.yml) | Test Postgres for pytest |

## Environment templates

| File | Purpose |
|------|---------|
| [/home/smirk/Tesslate-Studio/.env.example](../.env.example) | Variable list for local dev (`DEPLOYMENT_MODE=docker`). |
| [/home/smirk/Tesslate-Studio/.env.prod.example](../.env.prod.example) | Additional variables required by the prod and tunnel compose files. |

## Root tooling config

| File | Purpose |
|------|---------|
| [/home/smirk/Tesslate-Studio/package.json](../package.json) | Root workspace manifest (`tesslate-studio-root`); wires up husky and lint-staged. |
| [/home/smirk/Tesslate-Studio/package-lock.json](../package-lock.json) | npm lockfile for the root workspace. |
| [/home/smirk/Tesslate-Studio/pnpm-lock.yaml](../pnpm-lock.yaml) | pnpm lockfile (workspace packages such as `packages/tesslate-embed-sdk` use pnpm). |
| [/home/smirk/Tesslate-Studio/commitlint.config.js](../commitlint.config.js) | Extends `@commitlint/config-conventional` and enforces allowed commit types. |
| [/home/smirk/Tesslate-Studio/lint-staged.config.js](../lint-staged.config.js) | Runs per-package lint/format on staged files (wraps commands in `sh -c` so `cd dir && cmd` works). |
| [/home/smirk/Tesslate-Studio/.editorconfig](../.editorconfig) | Whitespace and indentation rules for every editor. |
| [/home/smirk/Tesslate-Studio/skills-lock.json](../skills-lock.json) | Locked skill pack versions used by the agent runtime. |

## Landing

| File | Purpose |
|------|---------|
| [/home/smirk/Tesslate-Studio/landing.html](../landing.html) | Static marketing landing page served by the frontend; Tailwind via CDN, no build step. |

## Related

- [docs/scripts/README.md](scripts/README.md) for all helper scripts.
- [docs/infrastructure/docker-compose/README.md](infrastructure/docker-compose/README.md) for the compose files.
- [docs/infrastructure/traefik/README.md](infrastructure/traefik/README.md) for Traefik wiring.
