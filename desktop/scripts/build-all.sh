#!/usr/bin/env bash
# Build the sidecar + Tauri installers for the host OS.
#
# Usage:
#   ./scripts/build-all.sh                       # debug build, unsigned
#   ./scripts/build-all.sh --release             # release build, unsigned
#   ./scripts/build-all.sh --release --signed    # release build with the Tauri
#                                                # updater key pulled from AWS
#                                                # Secrets Manager
#                                                # (tesslate/terraform/shared,
#                                                # variable `tauri_signing_private_key`)
#
# Signing is gated on env-var presence so unsigned local builds still work:
#   macOS  — APPLE_SIGNING_IDENTITY, APPLE_CERTIFICATE, APPLE_CERTIFICATE_PASSWORD,
#            APPLE_ID, APPLE_PASSWORD, APPLE_TEAM_ID
#   Windows — WINDOWS_SIGNING_CERT (path to .pfx), WINDOWS_SIGNING_CERT_PASSWORD
#   Tauri updater key — TAURI_SIGNING_PRIVATE_KEY (from `cargo tauri signer generate`).
#                      `--signed` fetches it from AWS Secrets Manager so contributors
#                      don't have to pass the env var by hand.
#
# When none of the signing env vars are set the script builds unsigned
# artifacts at desktop/src-tauri/target/*/bundle/.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DESKTOP_DIR="$(cd "$HERE/.." && pwd)"
REPO_ROOT="$(cd "$DESKTOP_DIR/.." && pwd)"
SIDECAR_DIR="$DESKTOP_DIR/sidecar"
VENV_DIR="$REPO_ROOT/.venv"
PY_VERSION="${OPENSAIL_PY_VERSION:-3.12}"

# AWS Secrets Manager secret holding the shared TF tfvars. The Tauri signing
# key is one of its variables — see k8s/terraform/shared/variables.tf.
SHARED_TFVARS_SECRET_ID="tesslate/terraform/shared"
SHARED_TFVARS_KEY="tauri_signing_private_key"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not on PATH — install with: brew install uv  (or curl -LsSf https://astral.sh/uv/install.sh | sh)" >&2
  exit 1
fi
if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "[build-all] creating .venv via uv (python $PY_VERSION)" >&2
  uv venv --python "$PY_VERSION" "$VENV_DIR"
fi
if ! VIRTUAL_ENV="$VENV_DIR" "$VENV_DIR/bin/python" -c \
    "import PyInstaller, app, tesslate_agent" >/dev/null 2>&1; then
  echo "[build-all] installing sidecar deps via uv pip" >&2
  VIRTUAL_ENV="$VENV_DIR" uv pip install pyinstaller \
    -e "$REPO_ROOT/packages/tesslate-agent" \
    -e "$REPO_ROOT/orchestrator"
fi

echo "[build-all] building sidecar" >&2
"$VENV_DIR/bin/python" "$SIDECAR_DIR/build_sidecar.py"

if ! command -v cargo >/dev/null 2>&1; then
  echo "cargo not on PATH — source \$HOME/.cargo/env or install rustup" >&2
  exit 1
fi
if ! cargo tauri --version >/dev/null 2>&1; then
  echo "[build-all] installing tauri-cli" >&2
  cargo install tauri-cli --version '^2.0' --locked
fi

cd "$DESKTOP_DIR/src-tauri"

# ── Argument parsing ─────────────────────────────────────────────────────────
# Recognise `--release` and `--signed` in any order, anywhere in the arg list;
# everything else is forwarded to `cargo tauri build` so callers can still pass
# tauri-cli flags through.
RELEASE_FLAG=""
USE_SIGNED_KEY=0
PASSTHROUGH_ARGS=()
while (( $# > 0 )); do
  case "$1" in
    --release)
      RELEASE_FLAG="--release"
      ;;
    --signed)
      USE_SIGNED_KEY=1
      ;;
    *)
      PASSTHROUGH_ARGS+=("$1")
      ;;
  esac
  shift
done

# ── Tauri updater key from AWS Secrets Manager (--signed) ────────────────────
# Tfvars are stored as a single text blob in Secrets Manager (see
# scripts/terraform/secrets.sh). We grep + sed the one HCL line we care about
# rather than pulling in `hcl2json`/jq-hcl just to read a single string. The
# grep stops at the first matching assignment so future duplicate keys would
# fail loud rather than silently picking the wrong one.
if (( USE_SIGNED_KEY )); then
  if [[ -n "${TAURI_SIGNING_PRIVATE_KEY:-}" ]]; then
    echo "[build-all] --signed: TAURI_SIGNING_PRIVATE_KEY already set in env, skipping AWS fetch" >&2
  else
    if ! command -v aws >/dev/null 2>&1; then
      echo "[build-all] --signed requires the AWS CLI (https://docs.aws.amazon.com/cli/)" >&2
      exit 1
    fi
    echo "[build-all] --signed: fetching $SHARED_TFVARS_KEY from $SHARED_TFVARS_SECRET_ID" >&2
    TFVARS_BLOB="$(aws secretsmanager get-secret-value \
      --secret-id "$SHARED_TFVARS_SECRET_ID" \
      --query SecretString \
      --output text 2>&1)" || {
      echo "[build-all] failed to fetch $SHARED_TFVARS_SECRET_ID — is your AWS session valid?" >&2
      echo "$TFVARS_BLOB" >&2
      exit 1
    }
    # Match: tauri_signing_private_key = "..."  (capture inside the quotes).
    KEY_LINE="$(printf '%s\n' "$TFVARS_BLOB" \
      | grep -E "^[[:space:]]*${SHARED_TFVARS_KEY}[[:space:]]*=" \
      | head -1)"
    if [[ -z "$KEY_LINE" ]]; then
      echo "[build-all] $SHARED_TFVARS_KEY not found in $SHARED_TFVARS_SECRET_ID" >&2
      echo "[build-all] add it to k8s/terraform/shared/terraform.shared.tfvars then re-upload with:" >&2
      echo "[build-all]   ./scripts/terraform/secrets.sh upload shared" >&2
      exit 1
    fi
    # Strip everything up to and including the first '"', then everything from
    # the last '"' onward — leaves the raw key body.
    KEY_VALUE="${KEY_LINE#*\"}"
    KEY_VALUE="${KEY_VALUE%\"*}"
    if [[ -z "$KEY_VALUE" ]]; then
      echo "[build-all] $SHARED_TFVARS_KEY is set but empty in $SHARED_TFVARS_SECRET_ID" >&2
      exit 1
    fi
    export TAURI_SIGNING_PRIVATE_KEY="$KEY_VALUE"
    # No passphrase by convention (`cargo tauri signer generate --password ""`);
    # set the var to empty so tauri-cli doesn't prompt.
    export TAURI_SIGNING_PRIVATE_KEY_PASSWORD="${TAURI_SIGNING_PRIVATE_KEY_PASSWORD:-}"
    echo "[build-all] --signed: TAURI_SIGNING_PRIVATE_KEY loaded (${#KEY_VALUE} bytes)" >&2
  fi
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
# Forward only the unrecognised flags — our own `--release` / `--signed` were
# already consumed by the parsing loop above. `PASSTHROUGH_ARGS` may be empty,
# which is fine.
if [[ -n "$RELEASE_FLAG" ]]; then
  exec cargo tauri build "${PASSTHROUGH_ARGS[@]}"
else
  exec cargo tauri build --debug "${PASSTHROUGH_ARGS[@]}"
fi
