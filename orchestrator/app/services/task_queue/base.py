"""
TaskQueue Protocol — common surface for background job dispatch.

Two backends:
- ArqTaskQueue (cloud): wraps an ARQ Redis pool.
- LocalTaskQueue (desktop): asyncio.Queue + in-proc workers + delayed dispatch.

The orchestrator fire-and-forget pattern is `await task_queue.enqueue(name, ...)`;
the returned job id is opaque and primarily used for logging / cancellation.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TaskQueue(Protocol):
    async def enqueue(
        self,
        name: str,
        *args: Any,
        _defer_by: float | None = None,
        **kwargs: Any,
    ) -> str:
        """Enqueue a job by handler name. `_defer_by` is seconds to delay."""
        ...


__all__ = ["TaskQueue"]
