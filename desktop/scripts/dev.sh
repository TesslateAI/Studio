#!/usr/bin/env bash
# Desktop dev launcher.
#
# Runs `cargo tauri dev` from desktop/src-tauri with the PyInstaller-frozen
# sidecar already built (Tauri's externalBin needs the binary on disk).
# The sidecar is rebuilt on demand when it's missing or stale vs. its
# entrypoint / spec. Frontend vite is started by Tauri itself via the
# `beforeDevCommand` hook in tauri.conf.json.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DESKTOP_DIR="$(cd "$HERE/.." && pwd)"
REPO_ROOT="$(cd "$DESKTOP_DIR/.." && pwd)"
SIDECAR_DIR="$DESKTOP_DIR/sidecar"
BIN_DIR="$DESKTOP_DIR/src-tauri/binaries"

case "$(uname -s)" in
  Linux*)   HOST_TRIPLE="x86_64-unknown-linux-gnu"  ;;
  Darwin*)  HOST_TRIPLE="$(uname -m)-apple-darwin"  ;;
  MINGW*|MSYS*|CYGWIN*) HOST_TRIPLE="x86_64-pc-windows-msvc" ;;
  *) echo "unsupported OS: $(uname -s)" >&2; exit 1 ;;
esac

BIN="$BIN_DIR/tesslate-studio-orchestrator-$HOST_TRIPLE"

need_rebuild=0
if [ ! -f "$BIN" ]; then
  need_rebuild=1
elif [ "$SIDECAR_DIR/entrypoint.py" -nt "$BIN" ] \
  || [ "$SIDECAR_DIR/spec/_common.py" -nt "$BIN" ]; then
  need_rebuild=1
fi

if [ "$need_rebuild" = "1" ]; then
  echo "[dev.sh] building sidecar for $HOST_TRIPLE" >&2
  python3 "$SIDECAR_DIR/build_sidecar.py"
else
  echo "[dev.sh] sidecar at $BIN is up to date" >&2
fi

if ! command -v cargo >/dev/null 2>&1; then
  echo "cargo not on PATH — source \$HOME/.cargo/env or install rustup" >&2
  exit 1
fi
if ! cargo tauri --version >/dev/null 2>&1; then
  echo "[dev.sh] installing tauri-cli" >&2
  cargo install tauri-cli --version '^2.0' --locked
fi

# Pin the sidecar port in dev so vite knows where to point. The frontend's
# API_URL resolution (app/src/config.ts) reads VITE_API_URL at dev time and
# falls back to http://localhost:8000 otherwise — ephemeral sidecar ports
# would leave the frontend pointing at the cloud docker-compose backend.
export TESSLATE_DESKTOP_PORT="${TESSLATE_DESKTOP_PORT:-43111}"
export VITE_API_URL="${VITE_API_URL:-http://127.0.0.1:$TESSLATE_DESKTOP_PORT}"
# Also tell Vite's dev-server proxy where to forward /api/* requests so that
# raw fetch() calls (which use a relative path resolved against localhost:5173)
# reach the sidecar instead of falling back to the docker default (port 8000).
export VITE_BACKEND_URL="${VITE_BACKEND_URL:-http://127.0.0.1:$TESSLATE_DESKTOP_PORT}"

# Preflight: kill anything holding the pinned sidecar port, the vite
# port, or any orphaned orchestrator/host process from a prior crashed
# run. Without this, a previous Tauri host that the user killed with
# Ctrl+C may have reparented its sidecar child to init(1), leaving port
# 43111 bound and causing "address already in use" on the next launch.
_cleanup_stale() {
  local port="$1"
  # fuser exits non-zero when nothing listens; swallow that.
  fuser -k -9 "${port}/tcp" >/dev/null 2>&1 || true
}
_cleanup_stale "$TESSLATE_DESKTOP_PORT"
_cleanup_stale 5173  # vite dev server
pkill -9 -f "tesslate-studio-orchestrator\$" >/dev/null 2>&1 || true
# Brief settle so the kernel actually releases the port.
sleep 1
echo "[dev.sh] sidecar pinned on $VITE_API_URL (stale processes cleaned)" >&2

cd "$DESKTOP_DIR/src-tauri"
exec cargo tauri dev "$@"
