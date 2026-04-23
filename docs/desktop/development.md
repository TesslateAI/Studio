# Desktop development setup

This page walks through standing up the OpenSail desktop client
(Tauri v2 + PyInstaller-frozen FastAPI sidecar) from a clean checkout.

If you already have the backend and frontend running in cloud mode, the
desktop client reuses both — there's no separate React or FastAPI
codebase; only the Tauri shell and the PyInstaller packaging are unique
to desktop.

## Toolchain

| Tool | Why | Install |
|---|---|---|
| Rust (stable) | Tauri host + cargo build | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` then `source $HOME/.cargo/env` |
| `cargo-tauri` CLI | `cargo tauri dev` / `cargo tauri build` entry points | `cargo install tauri-cli --version '^2.0' --locked` |
| Python 3.11+ | Orchestrator + sidecar entrypoint | system Python or pyenv |
| PyInstaller | Freeze the sidecar into a single binary | `pip install pyinstaller` (plus the orchestrator deps — see below) |
| pnpm | React frontend | `corepack enable && corepack prepare pnpm@latest --activate` |
| Node 20+ | pnpm runtime | `nvm install 20` or system package |

Linux-only system deps (Tauri WebKitGTK + tray-icon sysdeps):

```bash
sudo apt update
sudo apt install -y \
  libwebkit2gtk-4.1-dev libssl-dev libgtk-3-dev \
  libayatana-appindicator3-dev librsvg2-dev libsoup-3.0-dev \
  pkg-config build-essential
```

WSL2 works — WebKit renders under a software GL fallback (MESA/EGL
warnings on startup are harmless).

## One-time orchestrator install

The sidecar freezes the orchestrator into a PyInstaller bundle, so every
orchestrator dep must be importable from the Python that runs
`build_sidecar.py`. Editable installs are the simplest path:

```bash
# sibling tesslate-agent submodule first
pip install -e packages/tesslate-agent --break-system-packages
# then the orchestrator
pip install -e orchestrator --break-system-packages
```

`--break-system-packages` is only required on distros where pip refuses
to touch the system Python; skip it in a venv.

## Build the sidecar

The sidecar is a single `--onefile` PyInstaller executable that Tauri
spawns as `externalBin`. Build it once, then `cargo tauri dev` will
launch it:

```bash
python3 desktop/sidecar/build_sidecar.py
```

Output lands at
`desktop/src-tauri/binaries/tesslate-studio-orchestrator-<target-triple>`.
On first build this takes 2–3 minutes; subsequent builds reuse
PyInstaller caches and finish in under a minute.

`desktop/scripts/dev.sh` rebuilds the sidecar on demand when it's missing
or older than the entrypoint / shared spec.

## Run the desktop client

Fastest path — `cargo tauri dev` starts the React dev server for you,
spawns the sidecar, and opens the window:

```bash
cd desktop/src-tauri
cargo tauri dev
```

Or use the repo-level wrapper that handles sidecar freshness and
toolchain checks:

```bash
./desktop/scripts/dev.sh
```

**Do not** run `cargo run` directly — it skips the `beforeDevCommand`
that starts vite, so the window will load `http://localhost:5173`
against nothing and show a connection-refused error.

If you prefer manual control (useful for frontend-only iteration against
a previously-built sidecar):

```bash
# terminal 1
pnpm --dir app dev
# terminal 2 — once vite reports "Local: http://localhost:5173"
cd desktop/src-tauri && cargo run
```

## Verify the sidecar end-to-end

Run the frozen binary by itself to confirm the Python side boots
independently of Tauri. Useful when debugging migration, seeding, or
auth issues:

```bash
# clean slate
rm -rf /tmp/tesslate-studio-test
mkdir -p /tmp/tesslate-studio-test

OPENSAIL_HOME=/tmp/tesslate-studio-test \
  desktop/src-tauri/binaries/tesslate-studio-orchestrator-x86_64-unknown-linux-gnu
```

Expected output on a healthy boot:

- `TESSLATE_READY <port> <bearer>` on the first stdout line.
- Alembic migrations running to head.
- Marketplace seeds landing (≈10 "Created base:" / "Created agent:" lines).
- `Application startup complete.`
- `Uvicorn running on http://127.0.0.1:<port>`.

Smoke-test the API with the bearer from the ready line:

```bash
# read the bearer out of stdout or grep it from your log
curl -H "Authorization: Bearer $BEARER" "http://127.0.0.1:$PORT/api/desktop/tray-state"
```

A `{"runtimes":{...},"running_projects":[],"running_agents":[]}` response
confirms the sidecar-bearer loopback auth is wired correctly.

## Build installers

For a local installer that isn't signed — useful for smoke-testing
packaging:

```bash
./desktop/scripts/build-all.sh --release
```

Artifacts land under
`desktop/src-tauri/target/release/bundle/{deb,rpm,appimage,dmg,msi}/`
depending on your host OS. Each OS's full bundle only runs on that OS
(PyInstaller freezes a host-native Python, and the Tauri installer
formats are OS-specific) — cross-compiling is out of scope for this
repo; CI matrix builds are the intended path.

Signing + notarization (macOS Developer ID, Windows Authenticode, AppImage
GPG) is run by the release pipeline, not this script.

## Configuration

Environment variables the desktop sidecar reads at boot:

| Variable | Default | Purpose |
|---|---|---|
| `OPENSAIL_HOME` | per-OS default (macOS Application Support / Windows AppData / XDG) | Root for projects, SQLite DB, cache, marketplace installs |
| `DEPLOYMENT_MODE` | `desktop` (set by entrypoint) | Orchestrator mode selector |
| `DATABASE_URL` | `sqlite+aiosqlite:///$OPENSAIL_HOME/opensail.db` | Override to point at Postgres for debugging |
| `REDIS_URL` | `""` (empty) | Set to a real URL to opt back into Redis-backed pubsub + ARQ |
| `TESSLATE_DESKTOP_BEARER` | minted per launch | Loopback isolation token; Tauri host reads it from the handshake |
| `TESSLATE_CLOUD_TOKEN` | — | Override cloud bearer without going through the pairing deep-link |
| `TESSLATE_DESKTOP_HOST` | `127.0.0.1` | Override the bind host (don't) |
| `TESSLATE_DESKTOP_PORT` | ephemeral | Pin the port (don't — the Tauri host reads whichever the sidecar chose) |

See `/orchestrator/app/config.py` for the full set and
`/orchestrator/app/services/desktop_paths.py` for the per-OS `$OPENSAIL_HOME`
resolution.

## Troubleshooting

**"Could not connect to localhost" in the window** — you ran `cargo run`
directly. Use `cargo tauri dev` or `./desktop/scripts/dev.sh` so vite
actually starts.

**"cannot open shared object file: libpython3.12.so"** — the sidecar
binary was built with `--onedir` (sibling `_internal/` dir). Force a
`--onefile` rebuild: `rm -rf desktop/sidecar/dist desktop/src-tauri/binaries && python3 desktop/sidecar/build_sidecar.py`.

**`/tray-state` returns 401** — the tray poll is sending the wrong
bearer, or `TESSLATE_DESKTOP_BEARER` isn't set in the sidecar's
environment. Check the sidecar stdout for the `TESSLATE_READY` line —
the second field on that line is the bearer both the Tauri host and the
backend compare against.

**Alembic fails with "unknown function: now()"** — you're running against
a SQLite DB without the connect-time UDF. The orchestrator registers it
in `app/database.py` automatically when `DATABASE_URL` starts with
`sqlite`; if you're hitting this the sidecar is mis-wiring the URL.

**PyInstaller warning about `app.routers.public`** — expected. Those
modules import at collect-time and need Settings populated; the
warnings are suppressed but submodule collection skips affected packages.
The orchestrator still runs because we `collect_submodules` each
top-level package explicitly.

## Related

- `/desktop/CLAUDE.md` — desktop package entry point
- `/desktop/src-tauri/CLAUDE.md` — Rust host internals
- `/desktop/sidecar/CLAUDE.md` — PyInstaller packaging
- `/desktop/scripts/CLAUDE.md` — dev + build helpers
- `/docs/desktop/runtimes.md` — runtime probe + tray-state contract
- `/docs/desktop/cloud.md` — pairing + CloudClient
