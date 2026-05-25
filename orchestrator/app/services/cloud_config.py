"""Cloud companion endpoint config (desktop sidecar).

The desktop sidecar talks to a Tesslate Cloud companion for the LLM proxy,
marketplace catalog, and project sync. The endpoint defaults to the official
``https://your-domain.com`` but is user-overridable so self-hosters and
beta testers can point the desktop at their own cloud.

Resolution order (mirrors :mod:`token_store`):

  1. ``$TESSLATE_CLOUD_URL`` env var — Tauri-side / ops override; wins when set.
  2. JSON file at ``$OPENSAIL_HOME/cache/cloud_url.json`` — written by
     ``PUT /api/desktop/cloud-url``.
  3. ``settings.tesslate_cloud_url`` — the compiled-in default.

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
from urllib.parse import urlparse

from .desktop_paths import resolve_opensail_home

logger = logging.getLogger(__name__)

_ENV_VAR = "TESSLATE_CLOUD_URL"
_FILENAME = "cloud_url.json"


class InvalidCloudUrlError(ValueError):
    """Raised when a cloud URL fails validation."""


def _url_path() -> Path:
    return resolve_opensail_home() / "cache" / _FILENAME


def normalize_cloud_url(url: str) -> str:
    """Validate and canonicalize a cloud URL.

    Requires an ``http``/``https`` scheme and a host. Strips any trailing
    slash and any path/query/fragment so callers can append ``/api/...``
    deterministically.

    Raises:
        InvalidCloudUrlError: if the URL is malformed or uses a non-HTTP scheme.
    """
    if not url or not isinstance(url, str):
        raise InvalidCloudUrlError("cloud URL must be a non-empty string")

    candidate = url.strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https"):
        raise InvalidCloudUrlError("cloud URL must use http:// or https://")
    if not parsed.netloc:
        raise InvalidCloudUrlError("cloud URL must include a host")

    return f"{parsed.scheme}://{parsed.netloc}"


def get_cloud_url() -> str:
    """Return the effective cloud companion base URL (no trailing slash).

    Env var > on-disk override > compiled-in default. Always returns a value;
    a corrupt override file falls through to the default rather than raising.
    """
    from ..config import get_settings

    env = os.environ.get(_ENV_VAR)
    if env and env.strip():
        with contextlib.suppress(InvalidCloudUrlError):
            return normalize_cloud_url(env)

    path = _url_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            stored = data.get("url")
            if isinstance(stored, str) and stored:
                return normalize_cloud_url(stored)
        except (OSError, json.JSONDecodeError, InvalidCloudUrlError) as exc:
            logger.warning("cloud_config: ignoring bad override %s: %s", path, exc)

    return normalize_cloud_url(get_settings().tesslate_cloud_url)


def set_cloud_url(url: str) -> str:
    """Persist a cloud URL override atomically (0600 on POSIX).

    Returns the normalized URL that was stored. Does not touch the env var.

    Raises:
        InvalidCloudUrlError: if ``url`` fails validation.
    """
    normalized = normalize_cloud_url(url)

    path = _url_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps({"url": normalized}, separators=(",", ":"))
    fd, tmp_name = tempfile.mkstemp(prefix=".cloud_url.", dir=str(path.parent))
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

    return normalized


def clear_cloud_url() -> None:
    """Drop the on-disk override so resolution falls back to the default."""
    path = _url_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("cloud_config: failed to clear %s: %s", path, exc)
