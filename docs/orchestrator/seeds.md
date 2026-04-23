# Database Seeds

Two seed layers:

1. `orchestrator/app/seeds/` (package): idempotent functions invoked on startup and runnable standalone.
2. `orchestrator/scripts/` plus the top-level `orchestrator/seed_bases.py`: script entry points for ad-hoc and per-app seeding.

## `orchestrator/app/seeds/` Package

| File | Function | Purpose |
|------|----------|---------|
| `__init__.py` | `run_all_seeds()` | Startup seeder; orchestrates every function below. |
| `marketplace_bases.py` | `seed_marketplace_bases` | Official Tesslate project templates (Next.js 16, Vite+React+FastAPI, Vite+React+Go, Expo). |
| `community_bases.py` | `seed_community_bases` | ~63 community bases from open-source repos across ~32 framework categories. Linked to an "Open Source Community" account. |
| `marketplace_agents.py` | `seed_marketplace_agents`, `auto_add_librarian_agent_to_users` | Tesslate official account and default agents. Auto-enrolls Tesslate Agent + Librarian for all existing users. |
| `opensource_agents.py` | `seed_opensource_agents` | Six community agents (Code Analyzer, Doc Writer, Refactoring Assistant, Test Generator, API Designer, DB Schema Designer). |
| `mcp_servers.py` | `seed_mcp_servers` | Popular MCP servers (streamable-http, stdio, OAuth). Upsert on `slug`. |
| `skills.py` | `seed_skills` | `item_type='skill'` marketplace rows (open-source SKILL.md scrapes + Tesslate custom skills). |
| `themes.py` | `seed_themes` | Reads `seeds/themes/*.json` and upserts into `themes` table. Each JSON is self-contained. |
| `deployment_targets.py` | `seed_deployment_targets` | 22 deployment providers as `item_type='deployment_target'` rows so they render in the sidebar and deployment picker. |
| `workflow_templates.py` | `seed_workflow_templates` | Workflow template starters. Also runnable standalone via `python -m app.seeds.workflow_templates`. |

`seeds/themes/` holds 40+ self-contained `*.json` theme definitions (Andromeda, Dracula, Nord, Tokyo Night, Catppuccin, GitHub, etc.), each carrying its own colors, typography, spacing, animations, and metadata.

## Standalone Entry Points

| Script | Role |
|--------|------|
| `orchestrator/seed_bases.py` | Legacy Docker-compatible base seeder. Creates fullstack / frontend / backend marketplace bases directly. |
| `orchestrator/scripts/__init__.py` | Package marker. |
| `orchestrator/scripts/_seed_helpers.py` | Shared helpers that resolve a concrete `(user, team_id)` pair with an active `TeamMembership` so per-app seeders pass FK / role checks. |
| `orchestrator/scripts/seed_apps.py` | Unified Tesslate Apps seed runner. Walks `seeds/apps/registry.py:SEED_APPS` and delegates to each per-slug seeder. Non-zero exit on any app failure. |
| `orchestrator/scripts/seed_crm_app.py` | CRM demo app. Requires `TSL_APPS_DEV_AUTO_APPROVE=1` (or legacy `TSL_APPS_SKIP_APPROVAL=1`) and a cluster secret `llama-api-credentials`. |
| `orchestrator/scripts/seed_crm_with_postgres_app.py` | CRM + Postgres matrix demo. Declares `${secret:pg-creds/password}`; secret is per-install in the project namespace. |
| `orchestrator/scripts/seed_deer_flow_app.py` | ByteDance DeerFlow 2.0. Image-based; pulls `tesslate-deerflow:latest` from the minikube docker daemon. |
| `orchestrator/scripts/seed_hello_node_app.py` | hello-node: zero-dependency Node HTTP server (`server.js`). No build step. |
| `orchestrator/scripts/seed_hello_world_app.py` | Minimal hello-world app. |
| `orchestrator/scripts/seed_markitdown_app.py` | MarkItDown (Microsoft, FastAPI-wrapped). Image-based; requires `tesslate-markitdown:latest`. |
| `orchestrator/scripts/seed_mirofish_app.py` | MiroFish swarm-intelligence engine. Uses upstream `ghcr.io/666ghj/mirofish:latest`. |
| `orchestrator/scripts/seed_nightly_digest.py` | Nightly Activity Digest headless app. Requires `llama-api-credentials`. |

## Idempotency

All seed functions are intended to be idempotent. They upsert on stable keys (slug, email, id). Safe to run on every startup.

## Running

```bash
# Inside the backend container (Docker mode)
docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed_marketplace_bases.py

# Inside the backend pod (Kubernetes)
kubectl --context=tesslate -n tesslate exec deploy/tesslate-backend -- \
  env TSL_APPS_DEV_AUTO_APPROVE=1 python -m scripts.seed_hello_world_app
```

## Related

- `docs/apps/CLAUDE.md`: Tesslate Apps publishing pipeline.
- `orchestrator/app/seeds/__init__.py`: startup orchestration.
- `docs/guides/theme-system.md`: theme JSON schema.
