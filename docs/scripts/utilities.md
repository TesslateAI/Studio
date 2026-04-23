# Utility Scripts

> Catch-all for admin helpers, one-shot diagnostics, and smoke tests.

| Script | Purpose |
|--------|---------|
| `utilities/check_agents.py` | Dump every `MarketplaceAgent` row to stdout. Sanity-check after seeding. |
| `utilities/cleanup-local.py` | Complete local Docker cleanup: remove containers, project files, and wipe database data. Destructive. Pair with `scripts/docker.sh` for re-bring-up. |
| `utilities/generate_tool_info.py` | Instantiate an `IterativeAgent` and dump the full `_get_tool_info()` output. Useful for keeping tool docs in sync. |
| `utilities/make_user_admin.py` | Flip `is_admin` on a user by username. |
| `utilities/test_all_endpoints.sh` | Hit every API endpoint with a smoke-test payload. Run after a major refactor. |
| `utilities/verify_agent_abstraction.py` | Verify that `orchestrator/app/agent/factory.py` can instantiate every agent type stored in the DB. |

## Root-level helpers (out of `utilities/`)

See [README.md](README.md) for the full root table. Commonly-reached items:

| Script | Purpose |
|--------|---------|
| `scripts/create_admin.py` | Create or promote an admin user. |
| `scripts/generate-secret-key.py` | Print a fresh hex secret for `SECRET_KEY`. |
| `scripts/fix_uninitialized_containers.py` | Backfill `volume_name` on half-initialized containers. |
| `scripts/diagnose_container_return.py` | Time preview-URL return for a just-started project. |
| `scripts/secrets_migrate_audit.py` | Flag ambiguous or unmigrated secret references in container env. |
| `scripts/check_bases.py` | Print current marketplace bases from the dev DB. |
| `scripts/analyze_codebase.py` | Unused-code and duplicate analyzer (see [README_ANALYZER.md](../../scripts/README_ANALYZER.md)). |
| `scripts/analyze_deps.py` + `scripts/build_mermaid.py` | Dependency graph JSON + Mermaid render. |

## Related

- Agent factory: `orchestrator/app/agent/factory.py`
- Admin tooling context: [docs/orchestrator/routers/CLAUDE.md](../orchestrator/routers/CLAUDE.md)
