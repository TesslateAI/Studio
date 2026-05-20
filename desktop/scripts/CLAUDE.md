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
- `install.sh` — end-user installer for Linux + macOS, served for
  `curl -fsSL <host>/install.sh | sh`. Downloads the AppImage (Linux) or
  `.dmg` (macOS) and installs per-user, no sudo. Download host is a
  placeholder until release assets are published.
- `install.ps1` — end-user installer for Windows, served for
  `irm <host>/install.ps1 | iex`. Downloads the NSIS `-setup.exe` and
  runs it silently (per-user, no admin). Download host is a placeholder.
- `ci-local-test.sh` — runs the `Desktop Release` workflow's Linux build
  job locally via `act`, in a Docker container that mirrors the GitHub
  runner. Validates `.github/workflows/desktop-release.yml` before push.
  Windows/macOS legs can't run in a Linux container.

## Full setup
New developers should start at
[/docs/desktop/development.md](../../docs/desktop/development.md) for
the toolchain install (rustup, cargo-tauri, Linux sysdeps, PyInstaller)
and the one-time orchestrator + submodule editable installs.

## When to load
Running or modifying desktop build/dev flows.
