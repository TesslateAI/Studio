# PyInstaller spec for the macOS arm64 / x86_64 sidecar bundle.
#
#   cd desktop/sidecar
#   pyinstaller --noconfirm spec/macos.spec
#
# build_sidecar.py installs dist/tesslate-studio-orchestrator/ as
# desktop/src-tauri/binaries/tesslate-studio-orchestrator-<arch>-apple-darwin.
#
# Codesigning + notarization is run by the release pipeline, not here:
# `codesign --deep --sign "Developer ID Application: ..." dist/<bundle>`
# then submit to Apple notarytool. The pipeline lives outside this spec.

# ruff: noqa
import pathlib, sys

sys.path.insert(0, str(pathlib.Path(SPECPATH).resolve()))
from _common import build  # noqa: E402

a, pyz, exe = build(SPECPATH)
