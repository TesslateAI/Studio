# Desktop client (docs/desktop)

## Purpose
Landing page for OpenSail **desktop** (Tauri v2 + PyInstaller sidecar)
documentation. The desktop client reuses the same React frontend and FastAPI
orchestrator as cloud; this section covers only what's unique to the desktop
shell.

## Key files
- `/desktop/` — Tauri project + sidecar packaging
- `/desktop/CLAUDE.md` — entry into the desktop source tree
- `/orchestrator/app/services/desktop_paths.py` — `$OPENSAIL_HOME` resolver
- `/orchestrator/app/services/orchestration/factory.py` — per-project runtime dispatch

## Content pages
| Page | What it covers | Load when |
| ---- | -------------- | --------- |
| [development.md](development.md) | Toolchain install, sidecar build, `cargo tauri dev`, installer bundles, env vars, troubleshooting | First time standing up the desktop client locally |
| [runtimes.md](runtimes.md) | Runtime probe, per-project dispatch, port allocator, `$OPENSAIL_HOME` layout, tray endpoints | Touching the tray, runtime picker, local-runtime ports, or FS layout |
| [import.md](import.md) | `POST /api/desktop/import`, `import_path` schema, canonical-path dedup, POSIX symlink vs Windows `.tesslate-source` marker | Wiring the "open existing folder" flow or changing `ProjectCreate` |
| [cloud.md](cloud.md) | `CloudClient` pool/retry/breaker, `token_store` precedence, pairing endpoints, `tesslate://auth/callback` deep-link | Any change that calls the cloud from the sidecar |
| [marketplace.md](marketplace.md) | Dual-source listing, stale-while-revalidate cache, SHA-256 install pipeline, install/uninstall error map | Marketplace UI changes or installer edits |
| [sync.md](sync.md) | Pack exclusions, manifest shape, push conflict pre-check, atomic pull extraction, sync status | Working on `sync_client.py` or the sync routes |
| [agents.md](agents.md) | `TSK-NNNN` allocator, budget precedence, approval gate, `/agents/tickets`, `/agents/sessions` filter matrix | Agent worker, ticket UI, approval flows |
| [unified-workspace.md](unified-workspace.md) | `Directory` CRUD + dedup + git-root, AgentTask ↔ Directory, `HandoffBundle`, planned `open_in_ide` | Unified workspace UI or handoff wiring |

## Related contexts
- `/docs/orchestrator/orchestration/CLAUDE.md` — container orchestrators
- `/docs/orchestrator/services/` — services the desktop sidecar consumes

## When to load
Working on desktop-only code, packaging, tray, or the local ↔ cloud seams.
