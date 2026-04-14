"""
Desktop filesystem layout resolver.

Resolves `$TESSLATE_STUDIO_HOME` — the root directory the Tauri shell uses
for projects, cache, marketplace items, logs, and the SQLite database.

Resolution order:
  1. Explicit `settings.tesslate_studio_home` (if non-empty).
  2. `$TESSLATE_STUDIO_HOME` env var (if set).
  3. OS-default application data directory:
       - macOS:   ~/Library/Application Support/Tesslate Studio
       - Windows: %APPDATA%/Tesslate Studio
       - Linux:   $XDG_DATA_HOME/tesslate-studio (fallback: ~/.local/share/tesslate-studio)

Non-blocking: callers outside the desktop shell should not invoke this.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def resolve_studio_home(explicit: str | None = None) -> Path:
    """Return the Tesslate Studio home directory for the desktop shell.

    The directory is NOT created here — callers that need it materialized
    should call :func:`ensure_studio_home`.
    """
    if explicit:
        return Path(explicit).expanduser()

    env = os.environ.get("TESSLATE_STUDIO_HOME")
    if env:
        return Path(env).expanduser()

    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Tesslate Studio"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else home / "AppData" / "Roaming"
        return base / "Tesslate Studio"
    # Linux / other POSIX
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else home / ".local" / "share"
    return base / "tesslate-studio"


def ensure_studio_home(explicit: str | None = None) -> Path:
    """Resolve and create the studio home directory tree (projects/, cache/, logs/)."""
    root = resolve_studio_home(explicit)
    for sub in ("projects", "cache", "logs", "agents", "skills", "bases", "themes"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root
