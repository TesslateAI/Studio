"""Per-file write fence — serialize read-modify-write on the same path.

Two concurrent agents editing the same file would otherwise silently
overwrite each other (agent A reads X, agent B reads X, A writes, B writes).
We grab a short distributed lock keyed on (project_id, normalized_path) just
around the RMW sequence. Agents editing DIFFERENT files stay fully parallel.
"""

from __future__ import annotations

import contextlib
import logging
import os

logger = logging.getLogger(__name__)


def _normalize_path(path: str) -> str:
    return os.path.normpath(path).lstrip("./").replace("\\", "/")


@contextlib.asynccontextmanager
async def fence_file(project_id: str, file_path: str, *, ttl_seconds: int = 30):
    """Acquire a distributed lock around a single file's RMW.

    Falls back to a no-op when Redis / distributed lock is unavailable so
    single-process dev environments are never blocked.
    """
    if not project_id or not file_path:
        yield
        return

    try:
        from ....services.distributed_lock import get_distributed_lock

        dlock = get_distributed_lock()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[FILE-FENCE] distributed lock unavailable: {e}")
        yield
        return

    name = f"file:{project_id}:{_normalize_path(file_path)}"
    try:
        async with dlock.wait_for(name, ttl_seconds=ttl_seconds, max_wait_seconds=15.0):
            yield
    except TimeoutError:
        logger.warning(
            "[FILE-FENCE] timed out waiting for %s — proceeding without fence",
            name,
        )
        yield
