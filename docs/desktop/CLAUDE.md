# Desktop client (docs/desktop)

## Purpose

Landing page for OpenSail **desktop** (Tauri v2 + PyInstaller sidecar)
documentation. The desktop client reuses the same React frontend and FastAPI
orchestrator as cloud; this section covers only what is unique to the desktop
shell.

## Key entry files

| File | Role |
| ---- | ---- |
| `/desktop/CLAUDE.md` | Top-level entry into the desktop source tree |
| `/desktop/src-tauri/CLAUDE.md` | Rust Tauri host overview |
| `/desktop/src-tauri/tauri.conf.json` | App identity, window config, `externalBin` sidecar declaration, updater endpoint + pubkey |
| `/desktop/src-tauri/Cargo.toml` | Rust dependencies (tauri v2 + plugins) |
| `/desktop/src-tauri/capabilities/default.json` | Scoped plugin permissions (fs, shell, dialog, tray, notification, deep-link, stronghold) |
| `/desktop/sidecar/CLAUDE.md` | PyInstaller sidecar packaging overview |
| `/desktop/scripts/CLAUDE.md` | Build + dev helper scripts overview |
| `/orchestrator/app/services/desktop_paths.py` | `$OPENSAIL_HOME` resolver (matches Rust-side `tokens.rs`) |
| `/orchestrator/app/services/orchestration/factory.py` | Per-project runtime dispatch (`resolve_for_project`) |

## Rust sources (`desktop/src-tauri/src/`)

Every `.rs` module in the Tauri host, what it owns, and its public surface.

| Module | Responsibility | Key symbols |
| ------ | -------------- | ----------- |
| `main.rs` | Tauri app entry. Registers plugins (shell, fs, dialog, notification, deep-link, updater). Spawns sidecar, polls `/api/desktop/local-auth`, injects the local JWT into the WebView via `window.__TESSLATE_DESKTOP_TOKEN__`. Kills the sidecar on `ExitRequested` to avoid orphan PIDs. | `main()`, `fetch_local_user_token`, `inject_desktop_token` |
| `bootstrap.rs` | First-run bootstrap. Currently a no-op; the Python sidecar owns `ensure_opensail_home`. Placeholder for future host-side bundled assets. | (none) |
| `commands.rs` | Tauri `invoke` surface exposed to the React frontend. | `get_api_url`, `get_bearer`, `get_user_token`, `get_cloud_token`, `clear_cloud_token`, `is_cloud_paired`, `open_in_ide`, `start_dragging`, `minimize_window`, `toggle_maximize_window`, `close_window` |
| `sidecar.rs` | Spawns `tesslate-studio-orchestrator` via `tauri-plugin-shell`'s `externalBin`. Parses `TESSLATE_READY {port} {bearer}` handshake. 90s handshake timeout. Restart supervisor with exponential back-off (1s, 2s, 4s, 8s, 16s) up to 5 attempts; emits `sidecar-restarted` Tauri event on successful respawn. | `SidecarHandle`, `spawn`, `kill_on_exit`, `parse_ready` |
| `tray.rs` | System tray icon + "Open Studio" / "Quit" menu. Polls `GET /api/desktop/tray-state` every 5s, renders tooltip `OpenSail {N agents} {M projects}`. | `install`, `spawn_tooltip_poll`, `format_tooltip` |
| `tokens.rs` | Cloud pairing token store at `$OPENSAIL_HOME/cache/cloud_token.json`. Atomic write (tmp + rename), 0600 on POSIX. Mirrors Python `token_store.py`. `TESSLATE_CLOUD_TOKEN` env var overrides on-disk read. | `store_cloud_token`, `load_cloud_token`, `clear_cloud_token`, `is_paired` |
| `deep_link.rs` | Handles `tesslate://auth/callback?token=...` via `tauri-plugin-deep-link`. Persists token through `tokens.rs`, then POSTs it to the sidecar at `/api/desktop/auth/token`. | `register`, `extract_auth_token`, `dispatch_token` |
| `updater.rs` | Background auto-update via `tauri-plugin-updater`. Checks endpoint from `tauri.conf.json`, prompts the user with a native "Install / Later" dialog, downloads + installs + auto-restarts on confirm. Errors are non-fatal. | `check_in_background`, `check_and_prompt` |

## Sidecar sources (`desktop/sidecar/`)

| File | Role |
| ---- | ---- |
| `entrypoint.py` | PyInstaller-frozen FastAPI launcher. Resolves `$OPENSAIL_HOME`, loads `.env`, mints a stable `SECRET_KEY` at `$OPENSAIL_HOME/.secret_key` (0600), sets `DEPLOYMENT_MODE=desktop` + SQLite `DATABASE_URL`, runs alembic upgrade in-process, picks a free TCP port on 127.0.0.1 (or honors `TESSLATE_DESKTOP_PORT`), mints a per-launch bearer (`secrets.token_urlsafe(32)`), prints `TESSLATE_READY {port} {bearer}` and hands off to uvicorn. |
| `build_sidecar.py` | Per-OS PyInstaller driver. Detects host, selects `spec/{linux,macos,windows}.spec`, builds with `--onefile`, copies the resulting executable to `desktop/src-tauri/binaries/tesslate-studio-orchestrator-<target-triple>`. |
| `spec/_common.py` | Shared `Analysis` / `PYZ` / `EXE` blocks. Enumerates hidden imports (`app.*`, `tesslate_agent.*`, `litellm`, SQL drivers, `passlib`, `alembic`, `fastapi_users`). Bundles `alembic/`, `feature_flags/`, `app/agent/prompt_templates/`, and app `*.schema.json` as data files. Excludes `tkinter`, `matplotlib`, PyQt/PySide. Uses `--onefile` because Tauri `externalBin` ships a single file and `--onedir` sibling libs get lost on spawn. |
| `spec/linux.spec`, `spec/macos.spec`, `spec/windows.spec` | Per-OS specs that delegate to `_common.build(SPECPATH)`. Platform deviations (codesigning hooks, `.exe` suffix) live here; analysis list stays centralised. |

## Scripts (`desktop/scripts/`)

| File | Role |
| ---- | ---- |
| `dev.sh` | Dev launcher. Rebuilds the sidecar if missing or stale versus `entrypoint.py`, `spec/_common.py`, or any alembic migration. Installs `tauri-cli ^2.0` if absent. Pins `TESSLATE_DESKTOP_PORT=43111` (default) so Vite's `VITE_API_URL` / `VITE_BACKEND_URL` target it. Kills stale sidecars on the pinned port and on 5173 before `exec cargo tauri dev`. |
| `build-all.sh` | Installer builder. Rebuilds sidecar, then runs `cargo tauri build` (`--debug` by default, `--release` opt-in). Signing is env-var gated: `APPLE_*` (codesign + notarize), `WINDOWS_SIGNING_CERT*` (Authenticode), `TAURI_SIGNING_PRIVATE_KEY*` (update manifest). Unsigned local builds are supported. |

## Tests (`desktop/tests/`)

| File | Role |
| ---- | ---- |
| `smoke_test.py` | Two-tier suite. `@pytest.mark.automated` covers alembic upgrade against a fresh SQLite DB, idempotent re-upgrade, and sidecar `entrypoint` importability. `@manual` cases (skipped under `CI=true`) are self-documenting QA checklists for dev startup, project runtimes, import folder, Docker/K8s dropdown gating, tray notifications, concurrent agent sessions, marketplace toggle, and updater prompt. |

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
| [notifications.md](notifications.md) | OS notification dispatch from sidecar, tray fallback, event plumbing | Changing notification behavior |
| [permissions.md](permissions.md) | `.tesslate/permissions.json` read/write, agent permission gates | Touching desktop agent permissions |
| [tui.md](tui.md) | Headless agent CLI flow | Running agents without the GUI |
| [unified-workspace.md](unified-workspace.md) | `Directory` CRUD + dedup + git-root, AgentTask <-> Directory, `HandoffBundle`, planned `open_in_ide` | Unified workspace UI or handoff wiring |

## Related contexts

- `/docs/orchestrator/orchestration/CLAUDE.md`: container orchestrators
- `/docs/orchestrator/services/`: services the desktop sidecar consumes
- `/docs/packages/CLAUDE.md`: `tesslate-agent` runner bundled into the sidecar

## When to load

Working on desktop-only code, packaging, tray, deep-link, updater, PyInstaller bundling, or the local <-> cloud seams.
