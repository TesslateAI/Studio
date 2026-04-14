"""
Project sync storage + conflict detection.

The desktop client ships its local working tree as a zip plus a manifest of
`{path: sha256}`. This service:

1. Writes the zip blob to a content-addressable store (CAS), keyed by the
   SHA-256 of the blob. Duplicate pushes dedupe automatically.
2. Compares the incoming manifest to the project's current cloud-side manifest
   (the most recent `ProjectSnapshot` of `snapshot_type="sync"`) to surface
   conflicts — divergent files are returned, never auto-overwritten.

The storage backend is pluggable via `set_sync_storage` so tests can inject
an in-memory implementation. The default writes to disk under
`settings.project_sync_storage_root` (or `/tmp/tesslate-sync` when unset).
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class SyncStorage(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def exists(self, key: str) -> bool: ...


class FilesystemSyncStorage:
    """Content-addressable filesystem-backed storage."""

    def __init__(self, root: str | None = None) -> None:
        self._root = Path(root or os.environ.get("PROJECT_SYNC_STORAGE_ROOT", "/tmp/tesslate-sync"))
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Shard by first 2 chars of hash to keep directories small
        return self._root / key[:2] / key

    async def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.rename(path)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise FileNotFoundError(f"Sync blob not found: {key}")
        return path.read_bytes()

    async def exists(self, key: str) -> bool:
        return self._path(key).exists()


_storage: SyncStorage | None = None


def get_sync_storage() -> SyncStorage:
    global _storage
    if _storage is None:
        _storage = FilesystemSyncStorage()
    return _storage


def set_sync_storage(storage: SyncStorage | None) -> None:
    """Override the storage backend (tests)."""
    global _storage
    _storage = storage


def compute_blob_key(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def detect_conflicts(
    incoming_manifest: dict[str, str],
    cloud_manifest: dict[str, str] | None,
) -> list[dict[str, Any]]:
    """Return divergent files — paths that exist on both sides with different
    hashes. Cloud-only or client-only paths are not conflicts (they are adds
    from either side). Caller decides how to merge."""
    if not cloud_manifest:
        return []
    conflicts: list[dict[str, Any]] = []
    for path, incoming_hash in incoming_manifest.items():
        cloud_hash = cloud_manifest.get(path)
        if cloud_hash is not None and cloud_hash != incoming_hash:
            conflicts.append(
                {"path": path, "cloud_hash": cloud_hash, "incoming_hash": incoming_hash}
            )
    return conflicts


__all__ = [
    "FilesystemSyncStorage",
    "SyncStorage",
    "compute_blob_key",
    "detect_conflicts",
    "get_sync_storage",
    "set_sync_storage",
]
