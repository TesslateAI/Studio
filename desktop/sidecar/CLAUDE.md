# sidecar — PyInstaller orchestrator packaging

## Purpose
Freezes the FastAPI orchestrator into a single per-OS binary that Tauri
spawns as an `externalBin`. On boot the sidecar binds a loopback port,
emits a ready line with a per-launch bearer, and serves the same API the
cloud deployment serves.

## Build
Build the single-file bundle with `python3 build_sidecar.py` (takes 2–3
min cold). Output lands at
`../src-tauri/binaries/tesslate-studio-orchestrator-<target-triple>`.
Full toolchain + troubleshooting is in
[/docs/desktop/development.md](../../docs/desktop/development.md) —
including why we use `--onefile` rather than `--onedir` (Tauri's
externalBin ships one file; onedir's sibling `_internal/` shared libs
get lost on spawn).

## Key files
- `entrypoint.py` — `uvicorn` launcher with `DEPLOYMENT_MODE=desktop`; resolves `$OPENSAIL_HOME`; prints `TESSLATE_READY {port} {bearer}`.
- `build_sidecar.py` — per-OS PyInstaller driver.
- `spec/{macos,windows,linux}.spec` — PyInstaller specs (`--onedir`).

## Related contexts
- `../src-tauri/src/sidecar.rs` — the Rust supervisor that spawns this process
- `/orchestrator/app/config.py` — `deployment_mode="desktop"` + `opensail_home`

## When to load
Changing sidecar startup, PyInstaller bundling, or the ready-line contract.
