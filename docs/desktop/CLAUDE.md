# Desktop client (docs/desktop)

## Purpose
Landing page for Tesslate Studio **desktop** (Tauri v2 + PyInstaller sidecar)
documentation. The desktop client reuses the same React frontend and FastAPI
orchestrator as cloud; this section covers only what's unique to the desktop
shell.

## Key files
- `/desktop/` — Tauri project + sidecar packaging
- `/desktop/CLAUDE.md` — entry into the desktop source tree
- `/orchestrator/app/services/desktop_paths.py` — `$TESSLATE_STUDIO_HOME` resolver
- `/orchestrator/app/services/orchestration/factory.py` — per-project runtime dispatch

## Related contexts
- `/docs/orchestrator/orchestration/CLAUDE.md` — container orchestrators
- `/docs/orchestrator/services/` — services the desktop sidecar consumes

## When to load
Working on desktop-only code, packaging, tray, or the local ↔ cloud seams.
