"""
Edit History Ring Buffer

Global per-run tracking of the most recent file mutations so the ``file_undo``
tool can revert them. This is intentionally process-local and ephemeral:
it is cleared between runs (or when the buffer fills) and is not persisted.

Each entry captures:
    * ``path``          — the file path that was (or will be) mutated
    * ``prev_content``  — the content that was on disk BEFORE the mutation,
                          or ``None`` when the file did not previously exist
    * ``op``            — one of ``"write"``, ``"edit"``, ``"patch"``,
                          ``"delete"``, ``"move_src"``, ``"move_dst"``
    * ``timestamp``     — Unix epoch seconds captured at record time

The buffer is a fixed-size FIFO: once the capacity is reached, the oldest
entry is evicted on every new ``record`` call.

Thread/asyncio safety is provided by a single ``asyncio.Lock``. Callers
must be inside a running event loop to invoke the async API.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Literal

EditOp = Literal["write", "edit", "patch", "delete", "move_src", "move_dst"]

DEFAULT_CAPACITY = 100


@dataclass
class EditHistoryEntry:
    """One recorded mutation — see :class:`EditHistory` for semantics."""

    path: str
    prev_content: str | None
    op: EditOp
    timestamp: float


class EditHistory:
    """
    In-memory FIFO ring buffer of recent file mutations.

    The buffer is global to the process — every tool records here via
    :data:`EDIT_HISTORY`. Capacity is configurable at construction time;
    older entries are evicted once the capacity is exceeded.
    """

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        if capacity <= 0:
            raise ValueError("EditHistory capacity must be positive")
        self._capacity = capacity
        self._entries: deque[EditHistoryEntry] = deque(maxlen=capacity)
        self._lock = asyncio.Lock()

    @property
    def capacity(self) -> int:
        """Maximum number of entries retained."""
        return self._capacity

    async def record(
        self,
        path: str,
        prev_content: str | None,
        op: EditOp,
    ) -> None:
        """
        Append an entry for a mutation that is about to be (or has just
        been) applied. When the buffer is full the oldest entry is dropped.

        Args:
            path: File path relative to the project root (or absolute).
            prev_content: Contents of the file BEFORE the mutation, or
                ``None`` when the file did not previously exist.
            op: Kind of mutation being recorded.
        """
        async with self._lock:
            self._entries.append(
                EditHistoryEntry(
                    path=path,
                    prev_content=prev_content,
                    op=op,
                    timestamp=time.time(),
                )
            )

    async def pop_latest(self, path: str) -> EditHistoryEntry | None:
        """
        Remove and return the most recent entry for ``path``, or ``None``
        if there is no matching entry in the buffer.
        """
        async with self._lock:
            # Scan from the newest entry back to the oldest.
            idx = len(self._entries) - 1
            while idx >= 0:
                if self._entries[idx].path == path:
                    entry = self._entries[idx]
                    del self._entries[idx]
                    return entry
                idx -= 1
        return None

    async def all(self) -> list[EditHistoryEntry]:
        """
        Return a snapshot list of every entry currently in the buffer,
        oldest first. Mutations made after this call are not reflected
        in the returned list.
        """
        async with self._lock:
            return list(self._entries)

    async def clear(self) -> None:
        """Drop every entry in the buffer."""
        async with self._lock:
            self._entries.clear()


EDIT_HISTORY = EditHistory()

__all__ = ["EditHistory", "EditHistoryEntry", "EditOp", "EDIT_HISTORY", "DEFAULT_CAPACITY"]
