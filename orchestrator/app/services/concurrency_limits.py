"""Agent concurrency caps and per-user enqueue rate limiting.

Keeps the worker pool healthy when users spawn many parallel agents:

- ``user_max_concurrent_agents`` and ``project_max_concurrent_agents`` —
  hard ceilings enforced at enqueue time.
- ``user_enqueue_rate_per_10s`` — sliding-window rate limit to absorb
  spam-click bursts without back-pressuring the whole queue.

All state lives in Redis with self-expiring score-based ZSETs, so a crashed
worker that never removed its entry doesn't permanently reduce a user's
budget — stale entries age out after ``worker_job_timeout + 120s``.
"""

from __future__ import annotations

import logging
import time

from ..config import get_settings
from .cache_service import get_redis_client

settings = get_settings()

logger = logging.getLogger(__name__)


_USER_ACTIVE_KEY = "tesslate:agent:active:user:{user_id}"
_PROJECT_ACTIVE_KEY = "tesslate:agent:active:project:{project_id}"
_USER_RATE_KEY = "tesslate:agent:enqueue_rate:{user_id}"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _slot_ttl_ms() -> int:
    """Conservative age-out for active-slot entries.

    Slots should be removed on clean worker shutdown. This is the
    belt-and-suspenders TTL for crash-leaked slots.
    """
    return (settings.worker_job_timeout + 120) * 1000


class CapacityExceeded(Exception):
    """Raised when an enqueue would exceed a concurrency or rate limit."""

    def __init__(self, reason: str, limit: int, current: int):
        self.reason = reason
        self.limit = limit
        self.current = current
        super().__init__(f"{reason} (limit {limit}, current {current})")


async def _prune_and_count(key: str) -> int:
    """Drop expired slots and return live slot count. Returns 0 if Redis is down."""
    redis = await get_redis_client()
    if not redis:
        return 0
    now = _now_ms()
    cutoff = now - _slot_ttl_ms()
    try:
        await redis.zremrangebyscore(key, "-inf", cutoff)
        return int(await redis.zcard(key) or 0)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[CAP] prune/count failed on {key}: {e}")
        return 0


async def check_and_reserve_slot(user_id: str, project_id: str | None, task_id: str) -> None:
    """Enforce concurrency + rate caps, then atomically reserve a slot.

    Raises :class:`CapacityExceeded` if any limit would be breached. On success
    the caller owns a slot until :func:`release_slot` is invoked (worker finally).
    """
    redis = await get_redis_client()
    if not redis:
        return  # No Redis = single-pod local mode; caps not enforceable.

    now = _now_ms()
    window_start = now - 10_000

    user_key = _USER_ACTIVE_KEY.format(user_id=user_id)
    rate_key = _USER_RATE_KEY.format(user_id=user_id)

    # Rate limit first — cheaper check, catches spam before cap scan.
    try:
        await redis.zremrangebyscore(rate_key, "-inf", window_start)
        rate_count = int(await redis.zcard(rate_key) or 0)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[CAP] rate check failed: {e}")
        rate_count = 0
    if rate_count >= settings.user_enqueue_rate_per_10s:
        raise CapacityExceeded(
            "Too many requests — slow down and try again in a moment",
            settings.user_enqueue_rate_per_10s,
            rate_count,
        )

    # User-wide concurrent agents
    user_count = await _prune_and_count(user_key)
    if user_count >= settings.user_max_concurrent_agents:
        raise CapacityExceeded(
            "You have too many agents running — wait for one to finish",
            settings.user_max_concurrent_agents,
            user_count,
        )

    # Project-wide concurrent agents (skip for standalone chats)
    if project_id:
        proj_key = _PROJECT_ACTIVE_KEY.format(project_id=project_id)
        proj_count = await _prune_and_count(proj_key)
        if proj_count >= settings.project_max_concurrent_agents:
            raise CapacityExceeded(
                "This project has too many agents running — wait for one to finish",
                settings.project_max_concurrent_agents,
                proj_count,
            )

    # Reserve slots (add to ZSETs; score = now). Belt-and-suspenders EXPIRE
    # on the keys themselves so empty sets don't linger.
    try:
        await redis.zadd(user_key, {task_id: now})
        await redis.expire(user_key, settings.worker_job_timeout + 300)
        if project_id:
            proj_key = _PROJECT_ACTIVE_KEY.format(project_id=project_id)
            await redis.zadd(proj_key, {task_id: now})
            await redis.expire(proj_key, settings.worker_job_timeout + 300)
        await redis.zadd(rate_key, {task_id: now})
        await redis.expire(rate_key, 60)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[CAP] slot reservation failed: {e}")


async def release_slot(user_id: str, project_id: str | None, task_id: str) -> None:
    """Free the slot held by ``task_id``. Safe to call multiple times."""
    redis = await get_redis_client()
    if not redis:
        return
    try:
        await redis.zrem(_USER_ACTIVE_KEY.format(user_id=user_id), task_id)
        if project_id:
            await redis.zrem(_PROJECT_ACTIVE_KEY.format(project_id=project_id), task_id)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[CAP] slot release ignored error: {e}")
