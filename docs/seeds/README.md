# Seed Tesslate Apps

> Template Tesslate Apps that ship pre-seeded with every OpenSail install. Source of truth is [seeds/apps/registry.py](../../seeds/apps/registry.py); app trees live next to it.

## What is a seed app?

A seed app is a directory under `seeds/apps/<slug>/` containing:

- `app.manifest.json`: the 2025-02 manifest (id, slug, containers, surfaces, billing, state).
- The application tree (Next.js, Node, Python, Dockerfile, etc.).

Seed apps are:

- Installable by any user the moment the marketplace is seeded.
- Updated additively: drop a new folder in, add a registry row, and the publisher picks it up with no orchestrator code change.
- Excluded from Docker build context and bundle via `COMMON_SKIP_DIR_NAMES` in the registry (`node_modules`, `.next`, `.git`, `dist`, `__pycache__`).

The seed runner is `orchestrator/scripts/seed_apps.py`. It iterates [seeds/apps/registry.py](../../seeds/apps/registry.py), publishes the manifest + bundle to CAS, and records a `MarketplaceApp` + `AppVersion`. The shell helper [scripts/seed_all_apps.sh](../../scripts/seed_all_apps.sh) builds every external image, rolls the backend, and runs the seeder in one shot (minikube path).

## Catalog

| Slug | Path | Category | Tier / Model | Purpose |
|------|------|----------|--------------|---------|
| `hello-node` | `seeds/apps/hello-node/` | utility | 1 / always-on | Zero-dependency Node.js server. Proves the Apps runtime boots a live process (not a static page) with no npm install. |
| `crm-demo` | `seeds/apps/crm/` | productivity | 1 / per-installer | Next.js + Prisma + SQLite CRM with a chat-drawer Llama agent. Exercises the single-container per-install-volume path. |
| `crm-with-postgres` | `seeds/apps/crm-with-postgres/` | productivity | 1 / always-on | Matrix demo: Next.js web + Node API + Postgres service container with a CSI-backed volume, `env_injection` connector, and per-install secret reference. |
| `nightly-digest` | `seeds/apps/nightly_digest/` | automation | 0 / job-only | Headless cron-triggered digest via Llama. Exercises schedules, shared-singleton compute, and the HMAC webhook trigger endpoint. |
| `markitdown` | `seeds/apps/markitdown/` | utility | 1 / always-on | Microsoft MarkItDown wrapped in a FastAPI upload UI. Converts PDF, Office docs, audio, and YouTube URLs to Markdown for LLM pipelines. |
| `deer-flow` | `seeds/apps/deer-flow/` | research | 2 / always-on | ByteDance DeerFlow 2.0 open-source deep-research super-agent harness. Runs from a pre-built image; requires an LLM key. |
| `mirofish` | `seeds/apps/mirofish/` | research | 2 / always-on | Swarm-intelligence multi-agent prediction engine. Runs thousands of persona-driven agents and returns a prediction report. Requires an LLM key. |

## Registry entry shape

`SeedApp` (from [seeds/apps/registry.py](../../seeds/apps/registry.py)):

```python
@dataclass(frozen=True)
class SeedApp:
    slug: str
    assets_dir: Path
    manifest_filename: str = "app.manifest.json"
    description: str = ""
```

Add a new seed app by:

1. Dropping its tree into `seeds/apps/<slug>/` with an `app.manifest.json`.
2. Appending a `SeedApp(...)` entry to `SEED_APPS` in the registry.
3. (Optional) If the app needs a pre-built external image, add the build command to [scripts/seed_all_apps.sh](../../scripts/seed_all_apps.sh).

## App internals cheatsheet

| App | Notable files |
|-----|---------------|
| `hello-node` | `server.js` (zero-dep HTTP listener) |
| `crm` | `src/app/`, `src/components/`, `src/lib/`, `prisma/` |
| `crm-with-postgres` | `web/` (Next.js), `api/` (Node), `db/init.sql` |
| `deer-flow` | `Dockerfile`, `config.yaml`, `README.md` |
| `markitdown` | `Dockerfile`, `server.py` (FastAPI upload UI) |
| `mirofish` | Runs from prebuilt image `ghcr.io/666ghj/mirofish:latest`; no local tree beyond manifest |
| `nightly_digest` | `scripts/digest.js`, `package.json` |

## Related

- Apps platform context: [docs/apps/CLAUDE.md](../apps/CLAUDE.md)
- Seed runner: `orchestrator/scripts/seed_apps.py` (invoked by [scripts/seed_all_apps.sh](../../scripts/seed_all_apps.sh))
- Registry source: [seeds/apps/registry.py](../../seeds/apps/registry.py)
