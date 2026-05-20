#!/bin/sh
# OpenSail desktop installer for Linux and macOS.
#
# Usage:
#   curl -fsSL <DOWNLOAD_HOST>/install.sh | sh
#
# Linux  -> installs the AppImage to ~/.local/bin plus a desktop-menu entry.
# macOS  -> copies OpenSail.app into /Applications (or ~/Applications).
# Both installs are per-user and need no sudo / admin rights.
#
# Override the source or pinned version with environment variables:
#   OPENSAIL_INSTALL_BASE_URL=...   OPENSAIL_VERSION=0.1.0

set -eu

# ── configuration ─────────────────────────────────────────────────────────
# TODO(release): replace BASE_URL with the real download host once release
# assets are published. Until then this is a placeholder and the script will
# fail at the download step by design.
BASE_URL="${OPENSAIL_INSTALL_BASE_URL:-https://downloads.example.com/opensail}"
VERSION="${OPENSAIL_VERSION:-0.1.0}"

# ── helpers ───────────────────────────────────────────────────────────────
say()  { printf '%s\n' "opensail-install: $*"; }
die()  { printf '%s\n' "opensail-install: error: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "required tool not found: $1"; }

need uname
need curl

OS="$(uname -s)"
ARCH="$(uname -m)"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT INT TERM

download() {
  # download <url> <dest>
  say "downloading $1"
  # TODO(release): verify a published .sha256 alongside the artifact.
  curl -fSL --progress-bar "$1" -o "$2" || die "download failed: $1"
}

# ── Linux ─────────────────────────────────────────────────────────────────
install_linux() {
  case "$ARCH" in
    x86_64 | amd64) pkg_arch="amd64" ;;
    aarch64 | arm64) pkg_arch="aarch64" ;;
    *) die "unsupported Linux architecture: $ARCH" ;;
  esac

  artifact="OpenSail_${VERSION}_${pkg_arch}.AppImage"
  download "${BASE_URL}/${VERSION}/${artifact}" "$TMP/$artifact"

  bin_dir="$HOME/.local/bin"
  app_dir="$HOME/.local/share/applications"
  target="$bin_dir/opensail"
  mkdir -p "$bin_dir" "$app_dir"

  install -m 0755 "$TMP/$artifact" "$target"
  say "installed binary -> $target"

  # Desktop-menu entry. AppImages need FUSE; without it the app still runs
  # via `opensail --appimage-extract-and-run`.
  cat >"$app_dir/opensail.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=OpenSail
Comment=AI-powered application builder
Exec=$target
Terminal=false
Categories=Development;
EOF
  say "installed desktop entry -> $app_dir/opensail.desktop"

  case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *) say "note: $bin_dir is not on PATH — add it, or run $target directly" ;;
  esac
  say "done. launch with: opensail"
}

# ── macOS ─────────────────────────────────────────────────────────────────
install_macos() {
  case "$ARCH" in
    x86_64) dmg_arch="x64" ;;
    arm64) dmg_arch="aarch64" ;;
    *) die "unsupported macOS architecture: $ARCH" ;;
  esac

  need hdiutil

  artifact="OpenSail_${VERSION}_${dmg_arch}.dmg"
  download "${BASE_URL}/${VERSION}/${artifact}" "$TMP/$artifact"

  mount_point="$TMP/mnt"
  mkdir -p "$mount_point"
  hdiutil attach "$TMP/$artifact" -nobrowse -quiet -mountpoint "$mount_point" \
    || die "failed to mount $artifact"
  # Detach the image even if a later step fails.
  # shellcheck disable=SC2064
  trap "hdiutil detach '$mount_point' -quiet >/dev/null 2>&1 || true; rm -rf '$TMP'" EXIT INT TERM

  src_app="$(find "$mount_point" -maxdepth 1 -name '*.app' -print -quit)"
  [ -n "$src_app" ] || die "no .app bundle found inside $artifact"

  dest_dir="/Applications"
  [ -w "$dest_dir" ] || dest_dir="$HOME/Applications"
  mkdir -p "$dest_dir"

  app_name="$(basename "$src_app")"
  rm -rf "${dest_dir:?}/$app_name"
  cp -R "$src_app" "$dest_dir/"
  say "installed -> $dest_dir/$app_name"

  # The build is unsigned; strip the quarantine flag so Gatekeeper does not
  # block first launch with the "unidentified developer" dialog.
  xattr -dr com.apple.quarantine "$dest_dir/$app_name" 2>/dev/null || true

  say "done. launch OpenSail from $dest_dir."
}

# ── dispatch ──────────────────────────────────────────────────────────────
case "$OS" in
  Linux) install_linux ;;
  Darwin) install_macos ;;
  *) die "unsupported operating system: $OS" ;;
esac
