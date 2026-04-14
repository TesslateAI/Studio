#!/usr/bin/env bash
# Build the sidecar + Tauri installers for the host OS.
#
# For release builds pass `--release`; for a faster debug build omit it.
# Signed installers (macOS notarization, Windows Authenticode, AppImage
# GPG) are handled by the release pipeline — this script stops at the
# unsigned `.dmg` / `.msi` / `.AppImage` artifacts under
# `desktop/src-tauri/target/*/bundle/`.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DESKTOP_DIR="$(cd "$HERE/.." && pwd)"
SIDECAR_DIR="$DESKTOP_DIR/sidecar"

echo "[build-all] building sidecar" >&2
python3 "$SIDECAR_DIR/build_sidecar.py"

if ! command -v cargo >/dev/null 2>&1; then
  echo "cargo not on PATH — source \$HOME/.cargo/env or install rustup" >&2
  exit 1
fi
if ! cargo tauri --version >/dev/null 2>&1; then
  echo "[build-all] installing tauri-cli" >&2
  cargo install tauri-cli --version '^2.0' --locked
fi

cd "$DESKTOP_DIR/src-tauri"
if [[ "${1:-}" == "--release" ]]; then
  shift
  exec cargo tauri build "$@"
else
  exec cargo tauri build --debug "$@"
fi
