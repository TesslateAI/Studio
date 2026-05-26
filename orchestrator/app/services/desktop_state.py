"""Desktop sidecar onboarding state.

Tracks whether the user has completed (or dismissed) the first-run setup
choice — pair with Tesslate Cloud, bring your own keys, or skip. Persisted as
a JSON flag at ``$OPENSAIL_HOME/cache/desktop_state.json``.

No network I/O. File writes are atomic (tmp + rename), 0600 on POSIX.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

from .desktop_paths import resolve_opensail_home

logger = logging.getLogger(__name__)

_FILENAME = "desktop_state.json"


def _state_path() -> Path:
    return resolve_opensail_home() / "cache" / _FILENAME


def _read_state() -> dict:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("desktop_state: failed to read %s: %s", path, exc)
        return {}


def _write_state(state: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps(state, separators=(",", ":"))
    fd, tmp_name = tempfile.mkstemp(prefix=".desktop_state.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        if sys.platform != "win32":
            os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def is_first_run_complete() -> bool:
    """True once the user has made (or skipped) the first-run setup choice."""
    return bool(_read_state().get("first_run_complete"))


def mark_first_run_complete() -> None:
    """Record that the first-run setup choice has been made or dismissed."""
    state = _read_state()
    state["first_run_complete"] = True
    _write_state(state)
