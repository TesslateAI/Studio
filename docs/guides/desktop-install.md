# Running OpenSail as a Desktop App

A start-to-finish guide for installing, launching, and using the OpenSail
desktop client on macOS, Windows, and Linux. For contributor-focused details
on the Rust host and sidecar internals, see
[`/docs/desktop/development.md`](../desktop/development.md).

## 1. What you get

OpenSail desktop is a Tauri v2 native shell that wraps the same FastAPI
orchestrator and React UI that powers the cloud product. The orchestrator
ships as a PyInstaller-frozen Python sidecar; Tauri spawns it on a random
loopback port at launch and supervises it for the life of the window.

Key traits of the desktop profile:

- Single binary per OS. No Docker or Kubernetes required on the host.
- Local data plane. SQLite (via `aiosqlite`) replaces Postgres. An in-process
  `asyncio.Queue` and `LocalPubSub` replace Redis and ARQ.
- Per-project runtime. Each project picks one of three backends: `local`
  (host subprocesses), `docker` (Docker Compose on the host), or `k8s`
  (a remote cloud cluster reached through a paired API key).
- Same UI. The React app served on loopback is identical to cloud, so
  features like Monaco, the architecture panel, the marketplace, and the
  agent chat all render the same way.

## 2. System requirements

| OS | Minimum version | Notes |
| --- | --- | --- |
| macOS | 12 (Monterey) | Apple Silicon and Intel both supported. |
| Windows | 11 | Windows 10 22H2 is best-effort; WebView2 runtime required (preinstalled on 11). |
| Linux | Ubuntu 22.04 LTS / Fedora 38 / Debian 12 or newer | Needs `libwebkit2gtk-4.1`, `libssl`, `libayatana-appindicator3`, and `librsvg2`. |

Common to all platforms:

- 8 GB RAM minimum, 16 GB recommended once Docker or K8s projects run.
- 10 GB free disk for `$OPENSAIL_HOME` plus per-project volumes.
- A network connection is optional for local projects, required for cloud
  pairing, marketplace downloads, and the `k8s` runtime.

## 3. Install from release

Direct downloads live at
[github.com/TesslateAI/opensail/releases](https://github.com/TesslateAI/opensail/releases).
Pick the latest tagged release and grab the artifact for your OS.

### macOS (`.dmg`)

1. Download `OpenSail_<version>_aarch64.dmg` (Apple Silicon) or
   `OpenSail_<version>_x64.dmg` (Intel).
2. Open the DMG and drag `OpenSail.app` into `/Applications`.
3. First launch: right-click the app, pick "Open", then "Open" again at the
   Gatekeeper prompt. Shipped builds are codesigned with a Developer ID and
   notarized, so subsequent launches skip the prompt.

### Windows (`.msi`)

1. Download `OpenSail_<version>_x64_en-US.msi`.
2. Double-click and step through the installer. It installs to
   `%LOCALAPPDATA%\Programs\OpenSail` by default and pins a Start menu entry.
3. If SmartScreen flags the installer as "unrecognized", click "More info"
   then "Run anyway". Signed builds are Authenticode-signed; the warning
   fades after enough users launch the installer to build reputation.

### Linux (`.AppImage` or `.deb`)

AppImage (portable, no root):

```bash
chmod +x OpenSail_<version>_amd64.AppImage
./OpenSail_<version>_amd64.AppImage
```

Debian / Ubuntu (`.deb`):

```bash
sudo apt install ./opensail_<version>_amd64.deb
opensail
```

Fedora / RHEL (`.rpm`):

```bash
sudo dnf install ./opensail-<version>-1.x86_64.rpm
opensail
```

## 4. Install from source

Use this path if you want to track `main` or hack on the Tauri host. Full
toolchain detail lives in
[`/docs/desktop/development.md`](../desktop/development.md).

Prerequisites:

- Rust stable via rustup: `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`
- Node 20+ and pnpm: `corepack enable && corepack prepare pnpm@latest --activate`
- Python 3.11+ with `pip`
- Linux only: `sudo apt install libwebkit2gtk-4.1-dev libssl-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev libsoup-3.0-dev pkg-config build-essential`

One-time install:

```bash
git clone https://github.com/TesslateAI/opensail.git
cd opensail
pip install -e packages/tesslate-agent
pip install -e orchestrator
cargo install tauri-cli --version '^2.0' --locked
```

Run the dev loop (rebuilds the sidecar if stale, starts vite, opens the
window):

```bash
./desktop/scripts/dev.sh
```

Build an unsigned installer for your host OS:

```bash
./desktop/scripts/build-all.sh --release
```

Artifacts land under
`desktop/src-tauri/target/release/bundle/{dmg,msi,appimage,deb,rpm}/`.

## 5. First launch

On first open, the Tauri host performs these steps, all invisible to the user:

1. Spawns the frozen sidecar binary at `desktop/src-tauri/binaries/tesslate-studio-orchestrator-<target-triple>` on a free 127.0.0.1 port.
2. Parses the `TESSLATE_READY {port} {bearer}` handshake line from sidecar stdout.
3. Injects the bearer into the WebView as `window.__TESSLATE_DESKTOP_TOKEN__` so API calls work without the user signing in.
4. Installs a system tray icon showing "OpenSail {N agents} {M projects}" tooltip, polled every 5 seconds from `GET /api/desktop/tray-state`.
5. Runs Alembic migrations against the SQLite DB at `$OPENSAIL_HOME/opensail.db`.
6. Seeds the marketplace (agents, bases, skills, themes) on first boot only.

### Where `$OPENSAIL_HOME` lives

The sidecar resolves `$OPENSAIL_HOME` with the following precedence: the
`OPENSAIL_HOME` environment variable, otherwise an OS-specific default.
The resolver source is `orchestrator/app/services/desktop_paths.py`.

| OS | Default |
| --- | --- |
| macOS | `~/Library/Application Support/OpenSail/` |
| Windows | `%APPDATA%\OpenSail\` |
| Linux | `$XDG_DATA_HOME/tesslate-studio/` (typically `~/.local/share/tesslate-studio/`) |

Inside `$OPENSAIL_HOME`:

```
opensail.db                     SQLite database
.secret_key                     stable JWT signing key (0600)
projects/{slug}-{uuid}/         per-project roots for the local runtime
cache/cloud_token.json          paired cloud bearer
cache/marketplace.json          stale-while-revalidate marketplace cache
cache/ports.json                local-runtime port assignments
logs/                           sidecar and agent logs
agents/{slug}/manifest.json     installed marketplace agents
skills/, bases/, themes/        installed marketplace content
vapid.json                      VAPID keypair for web push
```

## 6. Pairing to a cloud instance

The desktop app works fully offline against local projects. Pairing to
`opensail.tesslate.com` (or a self-hosted cloud) unlocks extra features:

- Marketplace browse and install beyond what ships with the binary.
- Local to cloud project sync (push, pull, conflict resolution).
- The `k8s` per-project runtime (delegates to the cloud cluster on your behalf).
- Gateway-delivered agent notifications when the desktop window is closed.

To pair:

1. Open the cloud web UI, go to Settings, and generate a desktop pairing
   link. The cloud service mints a `tsk_` API key and returns a
   `tesslate://auth/callback?token=tsk_...` URL.
2. Click the link. The OS routes it to OpenSail via the registered
   `tesslate://` deep-link handler
   (`desktop/src-tauri/src/deep_link.rs`).
3. The handler persists the token through `tauri-plugin-stronghold` and
   posts it to the sidecar at `POST /api/desktop/auth/token`. The sidecar
   stores it at `$OPENSAIL_HOME/cache/cloud_token.json` with mode 0600 on
   POSIX.
4. `GET /api/desktop/auth/status` now returns `{paired: true, cloud_url: ...}`. The UI reflects that in Settings.

All cloud calls funnel through `CloudClient`
(`orchestrator/app/services/cloud_client.py`): bounded retries on 5xx, a
circuit breaker that opens after 5 failures in 60 seconds, and bearer
injection read from the token store at call time. Tokens never leave the
loopback boundary from the desktop side.

To unpair, call `DELETE /api/desktop/auth/token` or click "Disconnect" in
Settings. The token file is unlinked; environment-variable overrides are
not touched.

## 7. Per-project runtime selection

Every project row carries a `runtime` column. On desktop the picker in the
"Create project" modal offers three choices, each gated by a non-blocking
availability probe (`orchestrator/app/services/runtime_probe.py`):

| Runtime | When to pick | Requires |
| --- | --- | --- |
| `local` | Default. Fast iteration, no containers, one project per host port range. | Nothing beyond the app itself. |
| `docker` | You want the same container recipe used in cloud dev; multi-service projects with a Dockerfile per container. | Docker Desktop or Docker Engine on the host. The probe shells `docker info --format json` with a 3s timeout and a 30s cache. |
| `k8s` | Heavy projects, shared team clusters, production-like storage. The desktop dispatches through the cloud API to the remote cluster. | A paired cloud session. The probe currently stubs to `ok=false, reason="Cloud pairing required"` until the remote dispatch path is wired. |

Resolution happens in
`orchestrator/app/services/orchestration/factory.py` (`resolve_for_project`).
If `runtime` is null the desktop falls back to `LocalOrchestrator`. You can
switch a project's runtime at any time from the project sidebar; the
orchestrator will stop the current runtime and re-provision under the new
one.

The local runtime allocates host ports from
`settings.local_port_range_start` to `settings.local_port_range_end` (default
42000 to 42999) via `PortAllocator`
(`orchestrator/app/services/orchestration/local_ports.py`). Port assignments
persist at `$OPENSAIL_HOME/cache/ports.json` and are reclaimed when the
owning PID dies.

## 8. Adopting an existing folder

You can register any directory on disk as an OpenSail project without
copying files or scaffolding. Endpoint: `POST /api/desktop/import`
(`orchestrator/app/routers/desktop/projects.py`).

Request:

```json
{"name": "my-app", "path": "/home/me/code/my-app", "runtime": "local"}
```

The handler:

1. Expands `~` and resolves `os.path.realpath` to collapse symlinks. The
   canonical path lives on `Project.source_path`.
2. Rejects with 409 if another project already adopts the same canonical path.
3. Materializes the managed project root so the rest of the orchestrator
   can treat it like a scaffolded project:
   - POSIX: `os.symlink(source_path, project_root)`.
   - Windows: creates the managed directory and drops a `.tesslate-source`
     marker file pointing at the original path. Symlinks on Windows
     normally require elevation, so the marker is the portable fallback.
4. Detects the git root by walking parents looking for `.git` and stores
   it on `Directory.git_root` so the UI can group sessions by repo.

Sync, runtime dispatch, and agent tools all read `Project.source_path`
first, so imported projects stay exactly where they live on disk.

## 9. Permissions system

Each project keeps a `.tesslate/permissions.json` file that gates agent
capabilities. Read by `PermissionStore`
(`orchestrator/app/services/permission_store.py`) and by the TUI client.

Schema v1:

```json
{
  "schema_version": 1,
  "default_policy": "ask",
  "agents": {
    "*":        {"shell": "ask",   "network": "ask",   "git_push": "deny", "file_write": "allow", "process_spawn": "ask"},
    "my-agent": {"shell": "allow", "network": "deny",  "git_push": "deny", "file_write": "allow", "process_spawn": "deny"}
  },
  "budget": {"monthly_limit_usd": 20.0, "alert_threshold_pct": 80},
  "tui":    {"preferred_theme": "dark", "confirmation_mode": "inline"}
}
```

Resolution order for any capability check: `agents[agent_id][capability]`,
then `agents["*"][capability]`, then `default_policy`, then `ask` if nothing
matched.

Gate behavior by policy:

- `allow`: proceeds immediately.
- `deny`: returns a structured error to the agent. No user prompt.
- `ask`: routes through an approval gate. On the desktop this becomes a
  tray notification with an "Approve / Deny / Always" card. Clicking
  "Always" persists the decision via `persist_decision`, which writes back
  to `.tesslate/permissions.json` atomically.

For the underlying agent tool behavior and tool catalog, see
[`packages/tesslate-agent/docs/DOCS.md`](../../packages/tesslate-agent/docs/DOCS.md).

## 10. TUI mode

The same permission store and event stream power a headless terminal
client for SSH sessions, CI pipelines, or any environment without a GUI.

Start it:

```bash
export TESSLATE_API_URL="http://127.0.0.1:$PORT"   # from the sidecar's TESSLATE_READY line
export TESSLATE_BEARER="$BEARER"                    # same source, or a tsk_ cloud key
python -m tesslate_agent.tui
```

The TUI hits the same `GET /api/projects`, `POST /api/chat/agent/stream`,
and SSE streams the browser UI uses, so it works against both the local
sidecar and any paired cloud instance. When an `ask` gate fires, the
trajectory stream pauses and you respond inline with `y`, `n`, or `always`.

Details live at [`/docs/desktop/tui.md`](../desktop/tui.md).

## 11. Troubleshooting

### macOS

- "OpenSail is damaged and can't be opened": the DMG was downloaded with
  xattr quarantine and your network hops stripped the codesign signature.
  Redownload directly from GitHub Releases. If it persists, run
  `xattr -dr com.apple.quarantine /Applications/OpenSail.app`.
- "Developer cannot be verified" on older macOS builds: right-click the
  app, pick "Open", accept the prompt once. Notarized builds only trip
  this the first time.

### Windows

- SmartScreen "unrecognized app" warning: click "More info" then "Run
  anyway". New signing certificates take time to build reputation.
- Missing WebView2 runtime: only affects hand-rolled Windows 10 installs.
  Install `MicrosoftEdgeWebView2RuntimeInstaller` from Microsoft and
  relaunch.
- Blank window on launch: check `%APPDATA%\OpenSail\logs\` for the
  sidecar crash log. The most common cause is another process bound to
  the pinned dev port 43111; kill it or unset `TESSLATE_DESKTOP_PORT`.

### Linux

- `error while loading shared libraries: libssl.so.3`: install the
  system OpenSSL package (`sudo apt install libssl3` on Ubuntu 22.04,
  `sudo dnf install openssl` on Fedora).
- Tray icon missing on GNOME: install the
  [AppIndicator and KStatusNotifierItem Support](https://extensions.gnome.org/extension/615/appindicator-support/)
  extension. Tauri tray uses `libayatana-appindicator3` which GNOME
  ignores by default.
- WSL2 window is black: software GL fallback works but needs
  `WEBKIT_DISABLE_COMPOSITING_MODE=1` exported before launch.

### All OS: sidecar port conflicts

The sidecar picks a free port unless `TESSLATE_DESKTOP_PORT` is set. If
launches hang at the splash screen, check for a zombie
`tesslate-studio-orchestrator` process holding a port:

```bash
# POSIX
pkill -9 -f tesslate-studio-orchestrator
```

On Windows, use Task Manager or `taskkill /F /IM tesslate-studio-orchestrator.exe`.

## 12. Updating

Shipped builds include `tauri-plugin-updater`. On launch the host calls
the manifest at
`https://opensail.tesslate.com/desktop/releases/latest.json` (configured
in `desktop/src-tauri/tauri.conf.json`). When a newer version is
available:

1. The host prompts with a native "Install / Later" dialog. The prompt
   is in-app, not a web redirect.
2. On accept, it downloads the signed installer, verifies the signature
   against the pubkey baked into the binary, and installs in place.
3. The app restarts automatically. Your `$OPENSAIL_HOME`, paired cloud
   token, and projects persist across updates.

Update errors are non-fatal. If signature verification fails the user
stays on the current build and the error surfaces in the log.

Source-built copies do not auto-update. Re-run `git pull` and
`./desktop/scripts/build-all.sh --release`.

## 13. Where to next

- [`/docs/guides/docker-setup.md`](./docker-setup.md): run the cloud stack on Docker for testing the `docker` runtime.
- [`/docs/guides/minikube-setup.md`](./minikube-setup.md): stand up a local Kubernetes cluster to back the `k8s` runtime.
- [`/docs/orchestrator/routers/CLAUDE.md`](../orchestrator/routers/CLAUDE.md): gateway and messaging channel configuration, once your agent needs to reach Discord, Telegram, or Slack.
- [`/docs/apps/CLAUDE.md`](../apps/CLAUDE.md): publishing a Tesslate App built on top of a desktop project.
- [`/docs/desktop/development.md`](../desktop/development.md): deeper contributor workflow for sidecar packaging, updater signing, and runtime probes.
