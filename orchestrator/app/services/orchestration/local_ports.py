"""
Local-runtime port allocator.

Reserves host TCP ports for per-project / per-container dev servers under the
desktop local runtime. Persists assignments to
``$TESSLATE_STUDIO_HOME/cache/ports.json`` so that allocations survive
orchestrator restarts.

Concurrency:
    A module-level :class:`asyncio.Lock` guards all mutations. Callers must be
    running inside an event loop.

Persistence:
    Writes are atomic (tmp file + ``os.replace``). The file stores a list of
    ``{project_id, container_name, port, pid}`` entries. ``pid`` records the
    orchestrator PID that owned the allocation — :meth:`PortAllocator.reclaim_dead`
    sweeps entries whose pid is no longer live.

Range:
    Configured via ``settings.local_port_range_start`` / ``_range_end``
    (inclusive, default 42000–42999).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

_PORTS_CACHE_FILENAME = "ports.json"


def _pid_alive(pid: int) -> bool:
    """Return True if *pid* is a live process on this host."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it → still alive.
        return True
    except OSError:
        return False
    return True


class PortAllocator:
    """
    Thread-safe-ish (async-safe) port allocator for the local runtime.

    Not a singleton — consumers should instantiate once per orchestrator process.
    """

    def __init__(
        self,
        cache_dir: Path,
        range_start: int,
        range_end: int,
    ) -> None:
        if range_end < range_start:
            raise ValueError(
                f"local_port_range_end ({range_end}) < local_port_range_start ({range_start})"
            )
        self._cache_dir = Path(cache_dir)
        self._cache_path = self._cache_dir / _PORTS_CACHE_FILENAME
        self._range_start = int(range_start)
        self._range_end = int(range_end)
        self._lock = asyncio.Lock()
        # {(project_id_str, container_name): {"port": int, "pid": int}}
        self._assignments: dict[tuple[str, str], dict[str, int]] = {}
        self._loaded = False

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    def _ensure_loaded_locked(self) -> None:
        """Load the persisted state on first access. Caller must hold the lock."""
        if self._loaded:
            return
        self._loaded = True
        if not self._cache_path.exists():
            return
        try:
            raw = self._cache_path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[LOCAL-PORTS] Failed to load %s: %s", self._cache_path, exc)
            return

        entries = data.get("assignments", []) if isinstance(data, dict) else []
        for entry in entries:
            try:
                pid = int(entry.get("pid", 0))
                project_id = str(entry["project_id"])
                container = str(entry["container_name"])
                port = int(entry["port"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (self._range_start <= port <= self._range_end):
                continue
            self._assignments[(project_id, container)] = {"port": port, "pid": pid}

    def _persist_locked(self) -> None:
        """Atomically write the current state. Caller must hold the lock."""
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error("[LOCAL-PORTS] Cannot create cache dir %s: %s", self._cache_dir, exc)
            return

        payload: dict[str, Any] = {
            "range": {"start": self._range_start, "end": self._range_end},
            "assignments": [
                {
                    "project_id": pid_key,
                    "container_name": container,
                    "port": info["port"],
                    "pid": info["pid"],
                }
                for (pid_key, container), info in sorted(self._assignments.items())
            ],
        }

        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(self._cache_dir),
                prefix=f".{_PORTS_CACHE_FILENAME}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                json.dump(payload, tmp, indent=2)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = tmp.name
            os.replace(tmp_path, str(self._cache_path))
            tmp_path = None
        except OSError as exc:
            logger.error("[LOCAL-PORTS] Persist failed for %s: %s", self._cache_path, exc)
        finally:
            if tmp_path is not None:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def allocate(self, project_id: UUID | str, container_name: str) -> int:
        """
        Reserve a port for ``(project_id, container_name)``.

        Re-allocating the same pair returns the existing port (idempotent).

        Raises:
            RuntimeError: If the configured range is fully exhausted.
        """
        key = (str(project_id), container_name)
        async with self._lock:
            self._ensure_loaded_locked()

            existing = self._assignments.get(key)
            if existing is not None:
                return existing["port"]

            used = {info["port"] for info in self._assignments.values()}
            for candidate in range(self._range_start, self._range_end + 1):
                if candidate in used:
                    continue
                self._assignments[key] = {"port": candidate, "pid": os.getpid()}
                self._persist_locked()
                return candidate

            raise RuntimeError(
                f"[LOCAL-PORTS] Port range {self._range_start}-{self._range_end} exhausted "
                f"({len(used)} in use)"
            )

    async def release(self, project_id: UUID | str, container_name: str) -> None:
        """Free the port for a single ``(project, container)`` pair, if any."""
        key = (str(project_id), container_name)
        async with self._lock:
            self._ensure_loaded_locked()
            if self._assignments.pop(key, None) is not None:
                self._persist_locked()

    async def release_project(self, project_id: UUID | str) -> None:
        """Free all ports held by a given project."""
        target = str(project_id)
        async with self._lock:
            self._ensure_loaded_locked()
            victims = [k for k in self._assignments if k[0] == target]
            if not victims:
                return
            for k in victims:
                del self._assignments[k]
            self._persist_locked()

    async def reclaim_dead(self, pid_check: Callable[[int], bool] = _pid_alive) -> int:
        """
        Free any assignment whose owning pid is no longer alive.

        Returns:
            Count of reclaimed entries.
        """
        async with self._lock:
            self._ensure_loaded_locked()
            victims = [key for key, info in self._assignments.items() if not pid_check(info["pid"])]
            for k in victims:
                del self._assignments[k]
            if victims:
                self._persist_locked()
            return len(victims)

    async def get(self, project_id: UUID | str, container_name: str) -> int | None:
        """Return the currently assigned port for a pair, or ``None``."""
        key = (str(project_id), container_name)
        async with self._lock:
            self._ensure_loaded_locked()
            info = self._assignments.get(key)
            return info["port"] if info else None


# -----------------------------------------------------------------------------
# Module-level singleton (lazy)
# -----------------------------------------------------------------------------

_default: PortAllocator | None = None
_default_lock = asyncio.Lock()


async def get_default_allocator() -> PortAllocator:
    """Return the process-wide default allocator, constructing it lazily."""
    global _default
    if _default is not None:
        return _default
    async with _default_lock:
        if _default is None:
            from ...config import get_settings
            from ..desktop_paths import ensure_studio_home

            settings = get_settings()
            home = ensure_studio_home(settings.tesslate_studio_home or None)
            _default = PortAllocator(
                cache_dir=home / "cache",
                range_start=settings.local_port_range_start,
                range_end=settings.local_port_range_end,
            )
    return _default


def reset_default_allocator() -> None:
    """Test hook: drop the process-wide singleton so the next call rebuilds it."""
    global _default
    _default = None
