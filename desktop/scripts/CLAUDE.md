# desktop/scripts — build + dev helpers

## Purpose
Shell wrappers for common desktop workflows.

## Key files
- `dev.sh` — launch `pnpm tauri dev` against a live orchestrator (auto-resolves venv + frontend).
- `build-all.sh` — build the sidecar then produce signed installers per OS.

## When to load
Running or modifying desktop build/dev flows.
