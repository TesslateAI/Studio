"""
Cloud pairing token store (desktop sidecar).

Stores the long-lived ``tsk_`` API key minted by the cloud's
``POST /api/desktop/pair/complete`` endpoint. The eventual Tauri shell keeps
this token in OS Stronghold; the sidecar reads it via either:

  1. ``$TESSLATE_CLOUD_TOKEN`` env var (preferred when set — Tauri can inject
     it without ever touching disk), or
  2. A JSON file at ``$OPENSAIL_HOME/cache/cloud_token.json`` written
     by ``POST /api/desktop/auth/token``.

This module performs no network I/O. File writes are atomic (tmp + rename)
and chmod'd to ``0600`` on POSIX.
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

_ENV_VAR = "TESSLATE_CLOUD_TOKEN"
_FILENAME = "cloud_token.json"


def _token_path() -> Path:
    return resolve_opensail_home() / "cache" / _FILENAME


def get_cloud_token() -> str | None:
    """Return the cloud bearer token, or None if not paired.

    Env var takes precedence over the on-disk file.
    """
    env = os.environ.get(_ENV_VAR)
    if env:
        return env.strip() or None

    path = _token_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("token_store: failed to read %s: %s", path, exc)
        return None
    token = data.get("token")
    if isinstance(token, str) and token:
        return token
    return None


def set_cloud_token(token: str) -> None:
    """Persist ``token`` atomically to the cache file (0600 on POSIX).

    Does not touch the env var; the env var is a Tauri-side override only.
    """
    if not token or not isinstance(token, str):
        raise ValueError("token must be a non-empty string")

    path = _token_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps({"token": token}, separators=(",", ":"))
    fd, tmp_name = tempfile.mkstemp(prefix=".cloud_token.", dir=str(path.parent))
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


def clear_cloud_token() -> None:
    """Remove the on-disk token file. Env var override is left untouched."""
    path = _token_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("token_store: failed to clear %s: %s", path, exc)


def is_paired() -> bool:
    """True iff a token is available (env or file). No network call."""
    return get_cloud_token() is not None
