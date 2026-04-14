# PyInstaller spec for the Linux x86_64 sidecar bundle.
#
#   cd desktop/sidecar
#   pyinstaller --noconfirm spec/linux.spec
#
# build_sidecar.py drives this and installs dist/tesslate-studio-orchestrator/
# as desktop/src-tauri/binaries/tesslate-studio-orchestrator-x86_64-unknown-linux-gnu.

# ruff: noqa
import pathlib, sys

sys.path.insert(0, str(pathlib.Path(SPECPATH).resolve()))
from _common import build  # noqa: E402

a, pyz, exe = build(SPECPATH)
