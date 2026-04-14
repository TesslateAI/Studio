# desktop/scripts — build + dev helpers

## Purpose
Shell wrappers for common desktop workflows so developers don't have to
remember the sidecar rebuild / cargo-tauri install / vite-start dance.

## Key files
- `dev.sh` — rebuild the sidecar if stale, ensure `cargo tauri` is
  installed, then run `cargo tauri dev` from `src-tauri/`. The
  `beforeDevCommand` hook starts vite automatically. Pass through any
  extra args.
- `build-all.sh` — rebuild the sidecar and produce an unsigned installer
  bundle. Defaults to `--debug`; pass `--release` for the optimised
  artifact. Signing + notarization is handled by the release pipeline.

## Full setup
New developers should start at
[/docs/desktop/development.md](../../docs/desktop/development.md) for
the toolchain install (rustup, cargo-tauri, Linux sysdeps, PyInstaller)
and the one-time orchestrator + submodule editable installs.

## When to load
Running or modifying desktop build/dev flows.
