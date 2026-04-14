# sidecar — PyInstaller orchestrator packaging

## Purpose
Freezes the FastAPI orchestrator into a single per-OS binary that Tauri
spawns as an `externalBin`. On boot the sidecar binds a loopback port,
emits a ready line with a per-launch bearer, and serves the same API the
cloud deployment serves.

## Key files
- `entrypoint.py` — `uvicorn` launcher with `DEPLOYMENT_MODE=desktop`; resolves `$TESSLATE_STUDIO_HOME`; prints `TESSLATE_READY {port} {bearer}`.
- `build_sidecar.py` — per-OS PyInstaller driver.
- `spec/{macos,windows,linux}.spec` — PyInstaller specs (`--onedir`).

## Related contexts
- `../src-tauri/src/sidecar.rs` — the Rust supervisor that spawns this process
- `/orchestrator/app/config.py` — `deployment_mode="desktop"` + `tesslate_studio_home`

## When to load
Changing sidecar startup, PyInstaller bundling, or the ready-line contract.
