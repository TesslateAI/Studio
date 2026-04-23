# Seeds Agent Context

## Purpose

`seeds/apps/` contains the template Tesslate Apps that ship with every OpenSail install. Load this context when the user wants to:

- Add a new seed app.
- Change an existing seed app's manifest or code.
- Debug why a seed app failed to install.
- Understand the difference between seeds (static templates) and published apps (DB rows).

## Entry points

- Registry: [seeds/apps/registry.py](../../seeds/apps/registry.py)
- Seed runner: `orchestrator/scripts/seed_apps.py`
- Shell orchestrator: [scripts/seed_all_apps.sh](../../scripts/seed_all_apps.sh)

## Invariants

- Every seed app needs `app.manifest.json` at the schema version the runner understands (`2025-02` today).
- Additive-only: adding a new app must not require orchestrator code changes.
- `COMMON_SKIP_DIR_NAMES` controls what is excluded from the bundle: `node_modules`, `.next`, `.git`, `dist`, `__pycache__`. Do not push build output into the tree.

## Related Contexts

- [docs/seeds/README.md](README.md): full catalog and manifest shape
- [docs/apps/CLAUDE.md](../apps/CLAUDE.md): apps platform internals (publish, install, approval)
- [docs/orchestrator/services/CLAUDE.md](../orchestrator/services/CLAUDE.md): canonical seeders for the rest of the marketplace

## When to Load

- Implementing a new seed app
- Debugging an `AppInstallAttempt` failure for a seed slug
- Reviewing a PR that touches `seeds/apps/*`
