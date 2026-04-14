# Tesslate Studio Desktop

## Purpose
Tauri v2 shell that wraps the Tesslate Studio orchestrator and React frontend
as a native desktop app on macOS, Windows, and Linux. The orchestrator runs
as a PyInstaller-frozen **sidecar** process, launched and supervised by the
Tauri host. UI is the same React app (`app/`) served over loopback.

## Key files
- `src-tauri/` — Rust Tauri host (window, tray, sidecar supervision, deep-link auth).
- `sidecar/` — Python orchestrator packaging (PyInstaller specs, entrypoint).
- `scripts/` — build + dev helpers.
- Root `tauri.conf.json` lives at `src-tauri/tauri.conf.json`.

## Related contexts
- `/docs/desktop/CLAUDE.md` — user-facing desktop docs index
- `/orchestrator/app/services/desktop_paths.py` — `$TESSLATE_STUDIO_HOME` resolver
- `/orchestrator/app/services/orchestration/factory.py` — per-project runtime dispatch (`resolve_for_project`)

## When to load
- Building, running, or packaging the desktop client.
- Wiring the sidecar ↔ frontend bearer + port handshake.
- Touching tray, deep-link, or updater code.
