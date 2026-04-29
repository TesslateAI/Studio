"""
Hub identity helper.

`hub_id` is the stable UUID a federated marketplace announces in
`X-Tesslate-Hub-Id` on every response. Orchestrators pin it in
`MarketplaceSource.pinned_hub_id`; a mismatch on subsequent requests means the
URL has been hijacked or pointed at a different hub, and the source is
auto-disabled.

Resolution order:
    1. `Settings.hub_id` (explicit env var)
    2. Persisted file at `Settings.hub_id_file`
    3. Generate a fresh UUID4 and write it to the file (atomic rename)

This is intentionally process-local: even if the database is wiped, the file
keeps the hub identity stable. Orchestrators only need to re-pair when an
operator explicitly rotates `HUB_ID_FILE`.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from pathlib import Path

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_resolved: str | None = None


def _read_persisted(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning("could not read hub_id file %s: %s", path, exc)
        return None
    if not text:
        return None
    try:
        return str(uuid.UUID(text))
    except ValueError:
        logger.warning("hub_id file %s contains invalid UUID; regenerating", path)
        return None


def _write_persisted(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(value + "\n", encoding="utf-8")
    os.replace(tmp, path)


def resolve_hub_id(settings: Settings | None = None) -> str:
    """Return a stable hub_id, generating one on first boot if needed."""
    global _resolved
    if _resolved is not None:
        return _resolved

    settings = settings or get_settings()

    with _lock:
        if _resolved is not None:
            return _resolved

        if settings.hub_id:
            _resolved = str(uuid.UUID(settings.hub_id))
            return _resolved

        path = Path(settings.hub_id_file).expanduser()
        existing = _read_persisted(path)
        if existing:
            _resolved = existing
            return _resolved

        fresh = str(uuid.uuid4())
        try:
            _write_persisted(path, fresh)
            logger.info("generated new hub_id %s, persisted to %s", fresh, path)
        except OSError as exc:
            logger.warning("could not persist hub_id to %s: %s", path, exc)
        _resolved = fresh
        return _resolved


def reset_hub_id_cache() -> None:
    """Test helper: clear the in-process cache so resolve picks up new env."""
    global _resolved
    with _lock:
        _resolved = None
