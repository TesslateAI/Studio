"""
Recent Files Tracker.

Keeps a small ring buffer of file paths the agent has touched (read, edited,
viewed) per (user, project). Used by the context compactor to re-inject the
most-recently-accessed files after a compaction, so the agent resumes with
fresh state of the files it was working on — mirrors Claude Code's
post-compact attachment behaviour.

In-memory, per-process. Best-effort: a fresh worker pod starts with an empty
tracker and simply won't have files to re-inject on the first compaction. The
Redis-backed plan mirror is the authoritative cross-pod state; this tracker
is a local optimisation.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Any

_DEFAULT_RING_SIZE = 20


def _storage_key(context: dict[str, Any]) -> str:
    user_id = context.get("user_id", "unknown")
    project_id = context.get("project_id", "unknown")
    return f"user_{user_id}_project_{project_id}"


class RecentFileTracker:
    """Per-(user, project) ring buffer of recently-accessed file paths.

    The buffer is an OrderedDict so we can "touch" an existing path back to
    the most-recent position without duplicating entries.
    """

    def __init__(self, ring_size: int = _DEFAULT_RING_SIZE):
        self._ring_size = max(1, ring_size)
        self._buffers: dict[str, OrderedDict[str, None]] = {}
        self._lock = asyncio.Lock()

    async def record(self, context: dict[str, Any], path: str | None) -> None:
        """Record a file access. Silently ignores empty or non-string paths."""
        if not path or not isinstance(path, str):
            return
        key = _storage_key(context)
        async with self._lock:
            buf = self._buffers.setdefault(key, OrderedDict())
            # Move-to-end semantics: re-access bumps recency.
            buf.pop(path, None)
            buf[path] = None
            while len(buf) > self._ring_size:
                buf.popitem(last=False)

    async def record_many(self, context: dict[str, Any], paths: list[str]) -> None:
        """Record multiple file accesses in insertion order."""
        if not paths:
            return
        for p in paths:
            await self.record(context, p)

    async def recent(self, context: dict[str, Any], limit: int = 5) -> list[str]:
        """Return up to ``limit`` most-recently-accessed paths (newest first)."""
        if limit <= 0:
            return []
        key = _storage_key(context)
        async with self._lock:
            buf = self._buffers.get(key)
            if not buf:
                return []
            # OrderedDict is oldest→newest; reverse for newest first.
            return list(reversed(buf.keys()))[:limit]

    async def clear(self, context: dict[str, Any]) -> None:
        key = _storage_key(context)
        async with self._lock:
            self._buffers.pop(key, None)


_TRACKER: RecentFileTracker | None = None


def get_recent_file_tracker() -> RecentFileTracker:
    """Process-wide singleton accessor."""
    global _TRACKER
    if _TRACKER is None:
        _TRACKER = RecentFileTracker()
    return _TRACKER
