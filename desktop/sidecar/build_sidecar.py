"""PyInstaller driver for the desktop sidecar.

Drives the per-OS freeze (macOS arm64, Windows x64, Linux x64). Outputs
land under `desktop/src-tauri/binaries/tesslate-studio-orchestrator-<target-triple>`
to match `tauri.conf.json`'s `externalBin` declaration.
"""


def main() -> int:
    raise SystemExit("build_sidecar.py is not yet wired to PyInstaller")


if __name__ == "__main__":
    main()
