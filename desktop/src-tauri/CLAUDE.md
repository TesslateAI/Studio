# src-tauri — Rust Tauri host

## Purpose
Owns the desktop process lifecycle: main window, system tray, Python sidecar
supervision, deep-link auth callback, Stronghold token storage, and the
auto-updater.

## Setup
New to the stack? Read
[/docs/desktop/development.md](../../docs/desktop/development.md) for the
toolchain install (rustup, `cargo tauri`, Linux GTK/WebKit sysdeps) and the
one-command `cargo tauri dev` workflow. Running `cargo run` directly skips
vite and you'll see "Could not connect to localhost" — use the `tauri dev`
harness or `../scripts/dev.sh`.

## Key files
- `Cargo.toml` — Rust deps (tauri v2 + plugins).
- `tauri.conf.json` — app config, `externalBin` sidecar declaration.
- `capabilities/default.json` — scoped permissions (fs, shell, dialog, tray, notification, deep-link, stronghold).
- `src/main.rs` — entry; wires all modules.
- `src/sidecar.rs` — spawn orchestrator, parse `TESSLATE_READY {port} {bearer}`, health-check, restart on crash.
- `src/tray.rs` — tray icon + menu (Open Studio / Running Agents / Running Projects / Quit).
- `src/bootstrap.rs` — first-run copy of bundled marketplace + `$TESSLATE_STUDIO_HOME` tree.
- `src/tokens.rs` — Stronghold-backed token get/set (paired cloud credentials).
- `src/deep_link.rs` — `tesslate://auth/callback?token=...` handler.
- `src/updater.rs` — auto-update wiring.
- `src/commands.rs` — `invoke` commands (`get_api_url`, `get_bearer`, `open_folder`, `pick_dir`, etc.).

## Related contexts
- `../sidecar/CLAUDE.md` — sidecar packaging
- `/orchestrator/app/services/desktop_paths.py` — matching Python-side layout

## When to load
Working on Rust code, tauri.conf.json, capabilities, tray, or window lifecycle.
