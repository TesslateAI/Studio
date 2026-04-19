#!/usr/bin/env bash
# Build the sidecar + Tauri installers for the host OS.
#
# For release builds pass `--release`; for a faster debug build omit it.
#
# Signing is gated on env-var presence so unsigned local builds still work:
#   macOS  — APPLE_SIGNING_IDENTITY, APPLE_CERTIFICATE, APPLE_CERTIFICATE_PASSWORD,
#            APPLE_ID, APPLE_PASSWORD, APPLE_TEAM_ID
#   Windows — WINDOWS_SIGNING_CERT (path to .pfx), WINDOWS_SIGNING_CERT_PASSWORD
#   Tauri updater keys — TAURI_SIGNING_PRIVATE_KEY (from `cargo tauri signer generate`)
#
# When none of the signing env vars are set the script builds unsigned
# artifacts at desktop/src-tauri/target/*/bundle/.

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

RELEASE_FLAG=""
if [[ "${1:-}" == "--release" ]]; then
  shift
  RELEASE_FLAG="--release"
fi

# ── macOS codesign + notarize ─────────────────────────────────────────────────
if [[ "${APPLE_SIGNING_IDENTITY:-}" != "" ]]; then
  echo "[build-all] macOS signing enabled (identity: ${APPLE_SIGNING_IDENTITY})" >&2
  # tauri-cli picks up APPLE_* vars automatically when they are set.
  # APPLE_CERTIFICATE must be the base64-encoded .p12 content.
  # APPLE_CERTIFICATE_PASSWORD is the .p12 passphrase.
  # APPLE_ID + APPLE_PASSWORD + APPLE_TEAM_ID enable notarization.
  export APPLE_SIGNING_IDENTITY
  export APPLE_CERTIFICATE="${APPLE_CERTIFICATE:-}"
  export APPLE_CERTIFICATE_PASSWORD="${APPLE_CERTIFICATE_PASSWORD:-}"
  export APPLE_ID="${APPLE_ID:-}"
  export APPLE_PASSWORD="${APPLE_PASSWORD:-}"
  export APPLE_TEAM_ID="${APPLE_TEAM_ID:-}"
fi

# ── Windows Authenticode signing ──────────────────────────────────────────────
if [[ "${WINDOWS_SIGNING_CERT:-}" != "" ]]; then
  echo "[build-all] Windows signing enabled" >&2
  # tauri-cli reads WINDOWS_CERTIFICATE (base64 .pfx) + WINDOWS_CERTIFICATE_PASSWORD.
  # Map from the env vars we document in CI.
  export WINDOWS_CERTIFICATE="${WINDOWS_SIGNING_CERT}"
  export WINDOWS_CERTIFICATE_PASSWORD="${WINDOWS_SIGNING_CERT_PASSWORD:-}"
fi

# ── Tauri updater signing key (for update manifest) ───────────────────────────
if [[ "${TAURI_SIGNING_PRIVATE_KEY:-}" != "" ]]; then
  echo "[build-all] Tauri updater signing key present" >&2
  export TAURI_SIGNING_PRIVATE_KEY
  export TAURI_SIGNING_PRIVATE_KEY_PASSWORD="${TAURI_SIGNING_PRIVATE_KEY_PASSWORD:-}"
fi

# ── Build ─────────────────────────────────────────────────────────────────────
if [[ -n "$RELEASE_FLAG" ]]; then
  exec cargo tauri build "$@"
else
  exec cargo tauri build --debug "$@"
fi
