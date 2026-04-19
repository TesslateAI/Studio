"""
TaskQueue package — picks a backend based on whether Redis is configured.

    from app.services.task_queue import get_task_queue
    q = get_task_queue()
    await q.enqueue("execute_agent_task", payload_dict)

Backends:
- ArqTaskQueue (cloud): used when settings.redis_url is set.
- LocalTaskQueue (desktop): in-proc asyncio workers + delayed dispatch.
"""

from __future__ import annotations

from .arq_queue import ArqTaskQueue
from .base import TaskQueue
from .local_queue import LocalTaskQueue

_task_queue: TaskQueue | None = None


def get_task_queue() -> TaskQueue:
    """Return the process-wide TaskQueue backend."""
    global _task_queue
    if _task_queue is not None:
        return _task_queue

    from ...config import get_settings

    settings = get_settings()
    redis_url = getattr(settings, "redis_url", "") or ""
    if redis_url:
        _task_queue = ArqTaskQueue()
    else:
        max_jobs = getattr(settings, "worker_max_jobs", 5) or 5
        _task_queue = LocalTaskQueue(max_workers=max_jobs)
    return _task_queue


def _reset_task_queue_for_tests() -> None:
    global _task_queue
    _task_queue = None


__all__ = [
    "TaskQueue",
    "ArqTaskQueue",
    "LocalTaskQueue",
    "get_task_queue",
]
