"""
Local in-process TaskQueue — desktop sidecar.

- N async worker tasks drain a FIFO asyncio.Queue.
- Handlers are resolved by name through `app.services.agent_handlers`.
- Delayed jobs (`_defer_by`) are scheduled via asyncio.sleep + create_task.
- `cancel(job_id)` marks a pending job skipped (best-effort; running jobs
  are not interrupted here — use the pubsub cancellation signal for that).

Single-process by design; desktop runs one sidecar.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class _Job:
    job_id: str
    name: str
    args: tuple
    kwargs: dict
    cancelled: bool = field(default=False)


class LocalTaskQueue:
    def __init__(self, max_workers: int = 5) -> None:
        self._max_workers = max_workers
        self._queue: asyncio.Queue[_Job] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._delayed: dict[str, asyncio.Task] = {}
        self._pending: dict[str, _Job] = {}
        self._started = False
        self._handlers: dict[str, Callable[..., Any]] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        for i in range(self._max_workers):
            self._workers.append(asyncio.create_task(self._worker_loop(i)))
        logger.info("LocalTaskQueue started with %d workers", self._max_workers)

    async def stop(self) -> None:
        self._started = False
        for t in self._delayed.values():
            t.cancel()
        self._delayed.clear()
        for w in self._workers:
            w.cancel()
        for w in self._workers:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await w
        self._workers.clear()

    # ------------------------------------------------------------------
    # Handler registry
    # ------------------------------------------------------------------
    def _load_handlers(self) -> dict[str, Callable[..., Any]]:
        if self._handlers is not None:
            return self._handlers
        from ..agent_handlers import TASK_HANDLERS

        self._handlers = dict(TASK_HANDLERS)
        return self._handlers

    def register(self, name: str, handler: Callable[..., Any]) -> None:
        handlers = self._load_handlers()
        handlers[name] = handler

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------
    async def enqueue(
        self,
        name: str,
        *args: Any,
        _defer_by: float | None = None,
        **kwargs: Any,
    ) -> str:
        await self.start()
        job = _Job(job_id=uuid.uuid4().hex, name=name, args=args, kwargs=kwargs)
        self._pending[job.job_id] = job

        if _defer_by is None or _defer_by <= 0:
            await self._queue.put(job)
        else:
            self._delayed[job.job_id] = asyncio.create_task(self._schedule_delayed(job, _defer_by))
        return job.job_id

    def cancel(self, job_id: str) -> bool:
        job = self._pending.get(job_id)
        if job is None:
            return False
        job.cancelled = True
        delayed = self._delayed.pop(job_id, None)
        if delayed is not None:
            delayed.cancel()
        return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    async def _schedule_delayed(self, job: _Job, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            if not job.cancelled:
                await self._queue.put(job)
        except asyncio.CancelledError:
            pass
        finally:
            self._delayed.pop(job.job_id, None)

    async def _worker_loop(self, worker_idx: int) -> None:
        handlers = self._load_handlers()
        while self._started:
            try:
                job = await self._queue.get()
            except asyncio.CancelledError:
                return
            try:
                if job.cancelled:
                    continue
                handler = handlers.get(job.name)
                if handler is None:
                    logger.warning(
                        "LocalTaskQueue: no handler registered for %s (job %s)",
                        job.name,
                        job.job_id,
                    )
                    continue
                # ARQ handlers expect a ctx dict as first positional arg.
                ctx: dict[str, Any] = {
                    "job_id": job.job_id,
                    "task_queue": self,
                }
                try:
                    await handler(ctx, *job.args, **job.kwargs)
                except Exception:
                    logger.exception(
                        "LocalTaskQueue worker-%d: handler %s failed (job %s)",
                        worker_idx,
                        job.name,
                        job.job_id,
                    )
            finally:
                self._pending.pop(job.job_id, None)


__all__ = ["LocalTaskQueue"]
