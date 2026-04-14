"""PyInstaller driver for the desktop sidecar.

Picks the right PyInstaller spec for the host OS, runs the freeze, and
copies the resulting onedir bundle into
``desktop/src-tauri/binaries/tesslate-studio-orchestrator-<target-triple>``
to match ``tauri.conf.json``'s ``externalBin`` declaration.

Usage::

    python desktop/sidecar/build_sidecar.py
    # or, force a specific spec:
    python desktop/sidecar/build_sidecar.py --spec linux

The Tauri host expects the *executable* at the canonical path; PyInstaller
``--onedir`` produces a directory with the binary inside it, so we copy the
directory next to the binary symlink (Tauri reads the file but resolves
sibling shared libs from the same dir).
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
_SPEC_DIR = _HERE / "spec"
_TAURI_BINARIES = _REPO / "desktop" / "src-tauri" / "binaries"


def _detect_spec() -> str:
    sys_name = platform.system().lower()
    if sys_name == "darwin":
        return "macos"
    if sys_name == "windows":
        return "windows"
    return "linux"


def _detect_target_triple() -> str:
    """Match Cargo's host target triple convention."""
    sys_name = platform.system().lower()
    machine = platform.machine().lower()
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}.get(
        machine, machine
    )
    if sys_name == "darwin":
        return f"{arch}-apple-darwin"
    if sys_name == "windows":
        return f"{arch}-pc-windows-msvc"
    return f"{arch}-unknown-linux-gnu"


def _run_pyinstaller(spec: Path) -> Path:
    """Invoke PyInstaller; returns the resulting single-file executable.

    Specs use ``--onefile`` (no COLLECT block) so the output is one
    self-extracting binary at ``dist/<name>``. This is the form Tauri's
    ``externalBin`` can ship — ``--onedir`` ships sibling .so files that
    Tauri's spawn pipeline drops, breaking the Python bootloader.
    """
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--distpath", str(_HERE / "dist"),
        "--workpath", str(_HERE / "build"),
        str(spec),
    ]
    print("running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    return _HERE / "dist" / "tesslate-studio-orchestrator"


def _install_into_tauri(executable: Path, target_triple: str) -> Path:
    """Copy the single-file executable next to its target-triple suffix.

    Tauri resolves ``externalBin`` by suffixing the host triple onto the
    base path; we copy the executable under that name so the Tauri spawn
    matches.
    """
    _TAURI_BINARIES.mkdir(parents=True, exist_ok=True)
    # Clean up the obsolete onedir layout if it lingers from a prior build.
    legacy_dir = _TAURI_BINARIES / "tesslate-studio-orchestrator-bundle"
    if legacy_dir.exists():
        shutil.rmtree(legacy_dir)
    if not executable.exists():
        raise SystemExit(f"sidecar executable not produced at {executable}")
    target_exe = _TAURI_BINARIES / f"tesslate-studio-orchestrator-{target_triple}"
    if target_exe.exists() or target_exe.is_symlink():
        target_exe.unlink()
    shutil.copy2(executable, target_exe)
    target_exe.chmod(0o755)
    print(f"installed sidecar at {target_exe}")
    return target_exe


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--spec", choices=("linux", "macos", "windows"), default=_detect_spec()
    )
    parser.add_argument(
        "--target-triple",
        default=_detect_target_triple(),
        help="Override the cargo target triple suffix used in the output filename.",
    )
    args = parser.parse_args()
    spec_path = _SPEC_DIR / f"{args.spec}.spec"
    if not spec_path.exists():
        raise SystemExit(f"spec not found: {spec_path}")
    bundle_dir = _run_pyinstaller(spec_path)
    _install_into_tauri(bundle_dir, args.target_triple)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
