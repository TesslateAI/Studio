# Seed Scripts

> Wrappers for marketplace, theme, skill, agent, and MCP seed data. Canonical seeder bodies live under `orchestrator/app/seeds/`; these CLI scripts are thin shims so you can run one seed by name.

## How seeds run

- Most seeds run automatically on first backend startup via `run_all_seeds()`.
- For a clean-slate reset or a targeted re-seed, copy the script into the orchestrator container and invoke it. See [../../CLAUDE.md](../../CLAUDE.md) "Database Seeding" and the `docker-dev` skill for the full flow.
- Scripts are importable as modules and callable from tests.

## Catalog

| Script | What it seeds | Canonical implementation |
|--------|---------------|--------------------------|
| `seed/seed_marketplace_bases.py` | Initial marketplace base templates | `orchestrator/app/seeds/marketplace_bases.py` |
| `seed/seed_community_bases.py` | Community-contributed bases | `orchestrator/app/seeds/community_bases.py` |
| `seed/seed_marketplace_agents.py` | First-party agents | `orchestrator/app/seeds/marketplace_agents.py` |
| `seed/seed_opensource_agents.py` | Open-source agents | `orchestrator/app/seeds/opensource_agents.py` |
| `seed/seed_skills.py` | 15+ skill bodies | `orchestrator/app/seeds/skills.py` |
| `seed/seed_mcp_servers.py` | MCP server catalog (GitHub, Brave, Slack, Postgres, Filesystem, ...) | `orchestrator/app/seeds/mcp_servers.py` |
| `seed/seed_themes.py` | Themes from JSON under `orchestrator/app/seeds/themes/` | `orchestrator/app/seeds/themes.py` |
| `seed/seed_deployment_targets.py` | Vercel, Netlify, Cloudflare deployment targets | `orchestrator/app/seeds/deployment_targets.py` |
| `seed/seed_test_scenarios.py` | An ultra-plan test user with projects that exercise timeline DAG, snapshots, and sync | (self-contained) |
| `seed/simulate_activity.py` | Fires random file writes, reads, snapshots, syncs, and forks at the test user's projects | (self-contained) |
| `seed/update_tesslate_agent.py` | Update the existing Tesslate Agent row to open-source methodology prompt + toolset | (self-contained) |

## Destructive helpers

| Script | Effect |
|--------|--------|
| `seed/delete_all_agents.py` | Delete every marketplace agent + user associations. Use when resetting for a re-seed. |
| `seed/delete_seeded_agents.py` | Delete only agents that came from seed data. User-created agents survive. |
| `seed/bump_litellm_budgets.py` | Raise every user's LiteLLM budget cap to $10,000. One-shot after changing the default. |

## Seeding Tesslate Apps

`scripts/seed_all_apps.sh` (root-level) builds every external Tesslate App image, rolls the minikube backend, and seeds all 7 apps defined in [seeds/apps/registry.py](../../seeds/apps/registry.py). See [docs/seeds/README.md](../seeds/README.md) for per-app details.

## Related

- Canonical seeders: `orchestrator/app/seeds/` (see [docs/orchestrator/services/CLAUDE.md](../orchestrator/services/CLAUDE.md))
- Apps registry: [docs/seeds/README.md](../seeds/README.md)
- Database migration guidance: [docs/guides/database-migrations.md](../guides/database-migrations.md)
