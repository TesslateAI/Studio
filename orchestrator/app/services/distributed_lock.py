"""
Redis-based Distributed Lock

Prevents background loops from running on every pod when horizontally scaled.
Uses Redis SET NX EX pattern with Lua-based atomic release.

Usage:
    from app.services.distributed_lock import get_distributed_lock

    lock = get_distributed_lock()
    if lock:
        # Only one pod runs this loop at a time
        asyncio.create_task(lock.run_with_lock("cleanup", cleanup_loop, interval=300))
"""

import asyncio
import contextlib
import logging
import os
import uuid

logger = logging.getLogger(__name__)

# Lua script for atomic check-and-delete (only release if we hold the lock)
RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

LOCK_PREFIX = "tesslate:lock:"


class DistributedLock:
    """
    Redis-based distributed lock for coordinating background tasks across pods.

    Each pod generates a unique ID. Locks are acquired with SET NX EX
    and released atomically with a Lua script that checks ownership.
    """

    def __init__(self):
        # Unique ID for this pod instance
        self._pod_id = f"{os.environ.get('HOSTNAME', 'local')}:{uuid.uuid4().hex[:8]}"
        self._release_script_sha: str | None = None

    async def acquire(self, lock_name: str, ttl_seconds: int = 60) -> bool:
        """
        Try to acquire a distributed lock.

        Args:
            lock_name: Name of the lock
            ttl_seconds: Lock expiration in seconds (auto-releases if pod dies)

        Returns:
            True if lock acquired, False if already held by another pod
        """
        from .cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return True  # No Redis = single pod, always "acquire"

        key = f"{LOCK_PREFIX}{lock_name}"
        try:
            acquired = await redis.set(key, self._pod_id, nx=True, ex=ttl_seconds)
            return bool(acquired)
        except Exception as e:
            logger.warning(f"Failed to acquire lock {lock_name}: {e}")
            return False

    async def release(self, lock_name: str) -> bool:
        """
        Release a distributed lock (only if we hold it).

        Uses Lua script for atomic check-and-delete.

        Args:
            lock_name: Name of the lock

        Returns:
            True if released, False if we didn't hold it
        """
        from .cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return True

        key = f"{LOCK_PREFIX}{lock_name}"
        try:
            result = await redis.eval(RELEASE_LOCK_SCRIPT, 1, key, self._pod_id)
            return bool(result)
        except Exception as e:
            logger.warning(f"Failed to release lock {lock_name}: {e}")
            return False

    async def renew(self, lock_name: str, ttl_seconds: int = 60) -> bool:
        """
        Renew a lock's TTL (only if we hold it).

        Args:
            lock_name: Name of the lock
            ttl_seconds: New TTL in seconds

        Returns:
            True if renewed, False if we don't hold the lock
        """
        from .cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return True

        key = f"{LOCK_PREFIX}{lock_name}"
        try:
            # Check if we own the lock before renewing
            current_holder = await redis.get(key)
            if current_holder == self._pod_id:
                await redis.expire(key, ttl_seconds)
                return True
            return False
        except Exception as e:
            logger.warning(f"Failed to renew lock {lock_name}: {e}")
            return False

    async def run_with_lock(
        self,
        lock_name: str,
        loop_coro,
        lock_ttl: int = 120,
        renew_interval: int = 30,
    ):
        """
        Run a background loop only if this pod holds the distributed lock.

        The lock is acquired once and renewed periodically. If the pod dies,
        the lock expires and another pod picks it up.

        Args:
            lock_name: Name of the distributed lock
            loop_coro: The async loop coroutine to run (e.g., cleanup_loop)
            lock_ttl: Lock TTL in seconds (should be > renew_interval)
            renew_interval: How often to renew the lock
        """
        logger.info(
            f"[DLOCK] Attempting to acquire lock '{lock_name}' (pod={self._pod_id})"
        )

        while True:
            acquired = await self.acquire(lock_name, lock_ttl)

            if acquired:
                logger.info(
                    f"[DLOCK] Lock '{lock_name}' acquired by pod {self._pod_id}"
                )

                # Run the loop with periodic lock renewal
                try:
                    await self._run_with_renewal(
                        lock_name, loop_coro, lock_ttl, renew_interval
                    )
                except asyncio.CancelledError:
                    logger.info(f"[DLOCK] Lock '{lock_name}' task cancelled")
                    await self.release(lock_name)
                    raise
                except Exception as e:
                    logger.error(
                        f"[DLOCK] Loop '{lock_name}' crashed: {e}", exc_info=True
                    )
                    await self.release(lock_name)

                # If we get here, the loop exited — retry acquiring
                logger.warning(
                    f"[DLOCK] Lock '{lock_name}' released, will retry in 10s"
                )
                await asyncio.sleep(10)
            else:
                # Another pod holds the lock, wait and retry
                logger.debug(
                    f"[DLOCK] Lock '{lock_name}' held by another pod, retrying in {lock_ttl // 2}s"
                )
                await asyncio.sleep(lock_ttl // 2)

    async def _run_with_renewal(
        self,
        lock_name: str,
        loop_coro,
        lock_ttl: int,
        renew_interval: int,
    ):
        """
        Run the loop coroutine while periodically renewing the lock.
        """
        # Start the actual loop
        loop_task = asyncio.create_task(loop_coro())

        # Periodically renew the lock
        try:
            while not loop_task.done():
                await asyncio.sleep(renew_interval)
                renewed = await self.renew(lock_name, lock_ttl)
                if not renewed:
                    logger.warning(
                        f"[DLOCK] Lost lock '{lock_name}', stopping loop"
                    )
                    loop_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await loop_task
                    break
        except asyncio.CancelledError:
            loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await loop_task
            raise


# =============================================================================
# Global Instance
# =============================================================================

_distributed_lock: DistributedLock | None = None


def get_distributed_lock() -> DistributedLock:
    """Get the global DistributedLock instance."""
    global _distributed_lock
    if _distributed_lock is None:
        _distributed_lock = DistributedLock()
    return _distributed_lock
