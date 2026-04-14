# PyInstaller spec for the Windows x86_64 sidecar bundle.
#
#   cd desktop\sidecar
#   pyinstaller --noconfirm spec\windows.spec
#
# build_sidecar.py installs dist\tesslate-studio-orchestrator\ as
# desktop\src-tauri\binaries\tesslate-studio-orchestrator-x86_64-pc-windows-msvc.exe.
#
# Authenticode signing (signtool) is run by the release pipeline, not here.
# console=True is intentional — Tauri's externalBin reads stdout for the
# TESSLATE_READY handshake.

# ruff: noqa
import pathlib, sys

sys.path.insert(0, str(pathlib.Path(SPECPATH).resolve()))
from _common import build  # noqa: E402

a, pyz, exe = build(SPECPATH)
