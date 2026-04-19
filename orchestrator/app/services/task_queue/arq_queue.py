"""
ARQ-backed TaskQueue — cloud deployment.

Lazily constructs an ARQ Redis pool from `settings.redis_url` and forwards
`enqueue(name, ...)` to `pool.enqueue_job(name, ...)`. Delayed dispatch is
supported via ARQ's native `_defer_by` kwarg (datetime.timedelta).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class ArqTaskQueue:
    def __init__(self) -> None:
        self._pool: Any | None = None

    async def _get_pool(self) -> Any | None:
        if self._pool is not None:
            return self._pool

        from ...config import get_settings

        settings = get_settings()
        redis_url = getattr(settings, "redis_url", "") or ""
        if not redis_url:
            return None

        from arq import create_pool
        from arq.connections import RedisSettings

        parsed = urlparse(redis_url)
        self._pool = await create_pool(
            RedisSettings(
                host=parsed.hostname or "redis",
                port=parsed.port or 6379,
                database=int(parsed.path.lstrip("/") or "0"),
                password=parsed.password,
            )
        )
        logger.info("[TASK-QUEUE] ARQ Redis pool created")
        return self._pool

    async def enqueue(
        self,
        name: str,
        *args: Any,
        _defer_by: float | None = None,
        **kwargs: Any,
    ) -> str:
        pool = await self._get_pool()
        if pool is None:
            raise RuntimeError("ArqTaskQueue: Redis pool unavailable")

        enqueue_kwargs: dict[str, Any] = {}
        if _defer_by is not None:
            enqueue_kwargs["_defer_by"] = timedelta(seconds=_defer_by)
        enqueue_kwargs.update(kwargs)

        job = await pool.enqueue_job(name, *args, **enqueue_kwargs)
        return getattr(job, "job_id", "") if job else ""


__all__ = ["ArqTaskQueue"]
