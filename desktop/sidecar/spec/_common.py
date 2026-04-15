"""Shared PyInstaller analysis used by all per-OS specs.

Per-OS specs import :func:`build` and call it with their own ``SPECPATH``
to produce ``Analysis``, ``PYZ``, ``EXE``, ``COLLECT`` blocks. Keeping the
hidden-imports + datas list in one place avoids drift across platforms.

The console + onedir layout is identical on Linux / macOS / Windows; OS
deviations (codesigning hooks, .exe suffix) live in the per-OS spec.
"""

from __future__ import annotations

import pathlib

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyInstaller.building.api import EXE, PYZ
from PyInstaller.building.build_main import Analysis

HIDDEN_PACKAGES = (
    "app",
    "app.routers",
    "app.services",
    "app.services.orchestration",
    "app.services.pubsub",
    "app.services.task_queue",
    "app.services.gateway",
    "app.services.channels",
    "app.services.mcp",
    "app.services.deployment",
    "app.services.design",
    "app.types",
    "app.agent",
    "tesslate_agent",
    "tesslate_agent.agent",
    "tesslate_agent.agent.tools",
    "tesslate_agent.orchestration",
    "litellm",
    "asyncpg",
    "aiosqlite",
    "tiktoken",
    "tiktoken_ext",
    "tiktoken_ext.openai_public",
    "passlib",
    "passlib.handlers",
    "passlib.handlers.bcrypt",
    "bcrypt",
    "sqlalchemy.dialects",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.postgresql",
    "alembic",
    "fastapi_users",
    "fastapi_users.authentication",
)

DATA_PACKAGES = ("litellm", "tiktoken_ext", "tesslate_agent")

EXCLUDES = ("tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide2", "PySide6")


def _collect_hidden() -> list[str]:
    out: list[str] = []
    for pkg in HIDDEN_PACKAGES:
        out += collect_submodules(pkg)
    return out


def _collect_datas(orchestrator_dir: pathlib.Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for pkg in DATA_PACKAGES:
        out += collect_data_files(pkg)
    alembic_dir = orchestrator_dir / "alembic"
    if alembic_dir.is_dir():
        out.append((str(alembic_dir), "alembic"))
    feature_flags_dir = orchestrator_dir / "feature_flags"
    if feature_flags_dir.is_dir():
        out.append((str(feature_flags_dir), "feature_flags"))
    prompt_templates = orchestrator_dir / "app" / "agent" / "prompt_templates"
    if prompt_templates.is_dir():
        out.append((str(prompt_templates), "app/agent/prompt_templates"))
    return out


def build(spec_path: str, *, name: str = "tesslate-studio-orchestrator"):
    """Return the four PyInstaller blocks (Analysis, PYZ, EXE, COLLECT).

    Per-OS specs do::

        a, pyz, exe, coll = build(SPECPATH)

    and bind those names at module top level so PyInstaller picks them up.
    PyInstaller passes the spec's containing *directory* as ``SPECPATH``.
    """
    spec_dir = pathlib.Path(spec_path).resolve()
    sidecar_dir = spec_dir.parent
    repo_root = spec_dir.parents[2]
    orchestrator_dir = repo_root / "orchestrator"
    entry = sidecar_dir / "entrypoint.py"

    a = Analysis(
        [str(entry)],
        pathex=[str(orchestrator_dir)],
        binaries=[],
        datas=_collect_datas(orchestrator_dir),
        hiddenimports=_collect_hidden(),
        hookspath=[],
        excludes=list(EXCLUDES),
        noarchive=False,
        optimize=0,
    )
    pyz = PYZ(a.pure)
    # --onefile layout. Tauri's externalBin only ships a single file; with
    # --onedir the sibling _internal/ shared libs (libpython3.12.so etc.)
    # never reach target/debug at spawn time and the bootloader fails with
    # "cannot open shared object file". Single-file extracts at startup,
    # adds ~1s cold-boot overhead, and Just Works with externalBin.
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
    )
    return a, pyz, exe
