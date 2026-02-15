"""
Distributed Cache Service

Provides cross-replica caching using Redis with automatic fallback
to in-memory cache when Redis is unavailable.

Features:
- Redis backend for distributed caching across K8s replicas
- In-memory fallback for development and Redis failures
- TTL-based expiration
- Non-blocking - cache failures don't break the application
- Observable - logs cache hits, misses, and errors

Usage:
    from app.services.cache_service import cache

    # Basic get/set
    value = await cache.get("my_key")
    await cache.set("my_key", {"data": "value"}, ttl=300)

    # Get or compute
    models = await cache.get_or_set(
        "litellm_models",
        lambda: fetch_models_from_api(),
        ttl=300
    )
"""

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

# Type variable for generic caching
T = TypeVar("T")

# =============================================================================
# Redis Client Management
# =============================================================================

# Global Redis client (lazy initialized)
_redis_client = None
_redis_available: bool | None = None  # None = not checked, True/False = checked


async def get_redis_client():
    """
    Get or create Redis client.
    Returns None if Redis is not configured or unavailable.
    """
    global _redis_client, _redis_available

    # If we already know Redis is unavailable, don't retry
    if _redis_available is False:
        return None

    if _redis_client is not None:
        return _redis_client

    # Import config here to avoid circular imports
    from ..config import get_settings

    settings = get_settings()

    # Check if Redis URL is configured
    redis_url = getattr(settings, "redis_url", None) or ""
    if not redis_url:
        logger.info("Redis URL not configured, distributed caching disabled")
        _redis_available = False
        return None

    try:
        import redis.asyncio as redis

        _redis_client = redis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
        )
        # Test connection
        await _redis_client.ping()
        _redis_available = True
        logger.info(f"Redis cache connected: {redis_url}")
        return _redis_client
    except ImportError:
        logger.warning("redis package not installed, using in-memory cache only")
        _redis_available = False
        return None
    except Exception as e:
        logger.warning(f"Redis connection failed, falling back to in-memory cache: {e}")
        _redis_available = False
        return None


async def close_redis_client():
    """Close Redis connection (call on app shutdown)."""
    global _redis_client, _redis_available
    if _redis_client:
        with contextlib.suppress(Exception):
            await _redis_client.close()
        _redis_client = None
        _redis_available = None


# =============================================================================
# Cache Metrics
# =============================================================================

_cache_metrics = {
    "hits": 0,
    "misses": 0,
    "errors": 0,
    "local_hits": 0,
    "redis_hits": 0,
}


def get_cache_metrics() -> dict[str, Any]:
    """Get cache hit/miss statistics."""
    total = _cache_metrics["hits"] + _cache_metrics["misses"]
    hit_rate = (_cache_metrics["hits"] / total * 100) if total > 0 else 0
    return {
        **_cache_metrics,
        "total_requests": total,
        "hit_rate_percent": round(hit_rate, 2),
    }


def reset_cache_metrics():
    """Reset cache metrics (useful for testing)."""
    global _cache_metrics
    _cache_metrics = {
        "hits": 0,
        "misses": 0,
        "errors": 0,
        "local_hits": 0,
        "redis_hits": 0,
    }


# =============================================================================
# Distributed Cache Class
# =============================================================================


class DistributedCache:
    """
    Distributed cache with Redis backend and in-memory fallback.
    Provides consistent API regardless of Redis availability.
    """

    def __init__(self, namespace: str = "tesslate"):
        self.namespace = namespace
        # In-memory fallback cache (per-process)
        # Stores (value, expires_at) tuples
        self._local_cache: dict[str, tuple[Any, float]] = {}

    def _make_key(self, key: str) -> str:
        """Create namespaced Redis key."""
        return f"{self.namespace}:{key}"

    async def get(self, key: str) -> Any | None:
        """
        Get value from cache.
        Tries Redis first, falls back to local cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        full_key = self._make_key(key)
        redis_client = await get_redis_client()

        # Try Redis first
        if redis_client:
            try:
                value = await redis_client.get(full_key)
                if value:
                    _cache_metrics["hits"] += 1
                    _cache_metrics["redis_hits"] += 1
                    logger.debug(f"Cache HIT (redis): {key}")
                    return json.loads(value)
            except Exception as e:
                logger.warning(f"Redis GET failed for {key}: {e}")
                _cache_metrics["errors"] += 1

        # Fallback to local cache
        if full_key in self._local_cache:
            value, expires_at = self._local_cache[full_key]
            if time.time() < expires_at:
                _cache_metrics["hits"] += 1
                _cache_metrics["local_hits"] += 1
                logger.debug(f"Cache HIT (local): {key}")
                return value
            else:
                # Expired - remove from cache
                del self._local_cache[full_key]

        _cache_metrics["misses"] += 1
        logger.debug(f"Cache MISS: {key}")
        return None

    async def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        """
        Set value in cache with TTL.
        Writes to both Redis and local cache for resilience.

        Args:
            key: Cache key
            value: Value to cache (must be JSON serializable)
            ttl: Time to live in seconds (default 5 minutes)

        Returns:
            True if at least one cache was updated
        """
        full_key = self._make_key(key)
        serialized = json.dumps(value)

        # Always update local cache
        self._local_cache[full_key] = (value, time.time() + ttl)

        # Try Redis
        redis_client = await get_redis_client()
        if redis_client:
            try:
                await redis_client.setex(full_key, ttl, serialized)
                logger.debug(f"Cache SET (redis+local): {key}, TTL={ttl}s")
                return True
            except Exception as e:
                logger.warning(f"Redis SET failed for {key}: {e}")
                _cache_metrics["errors"] += 1

        logger.debug(f"Cache SET (local only): {key}, TTL={ttl}s")
        return True

    async def delete(self, key: str) -> bool:
        """
        Delete value from cache.

        Args:
            key: Cache key

        Returns:
            True if deleted from at least one cache
        """
        full_key = self._make_key(key)

        # Remove from local cache
        deleted_local = full_key in self._local_cache
        if deleted_local:
            del self._local_cache[full_key]

        # Try Redis
        redis_client = await get_redis_client()
        if redis_client:
            try:
                await redis_client.delete(full_key)
                logger.debug(f"Cache DELETE: {key}")
                return True
            except Exception as e:
                logger.warning(f"Redis DELETE failed for {key}: {e}")
                _cache_metrics["errors"] += 1

        return deleted_local

    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Any],
        ttl: int = 300,
    ) -> Any:
        """
        Get from cache or compute and store.
        Factory function is only called on cache miss.

        Args:
            key: Cache key
            factory: Function to compute value on cache miss
                     Can be sync or async
            ttl: Time to live in seconds

        Returns:
            Cached or computed value
        """
        # Try to get from cache
        value = await self.get(key)
        if value is not None:
            return value

        # Compute value
        if asyncio.iscoroutinefunction(factory):
            value = await factory()
        else:
            value = factory()

        # Store in cache
        await self.set(key, value, ttl)
        return value

    async def clear_namespace(self) -> int:
        """
        Clear all keys in this namespace.
        Use with caution in production.

        Returns:
            Number of keys deleted
        """
        # Clear local cache for this namespace
        prefix = f"{self.namespace}:"
        local_keys = [k for k in self._local_cache if k.startswith(prefix)]
        for k in local_keys:
            del self._local_cache[k]

        # Try Redis
        redis_client = await get_redis_client()
        if redis_client:
            try:
                pattern = f"{self.namespace}:*"
                keys = await redis_client.keys(pattern)
                if keys:
                    await redis_client.delete(*keys)
                    logger.info(f"Cleared {len(keys)} keys from Redis namespace {self.namespace}")
                    return len(keys)
            except Exception as e:
                logger.warning(f"Redis clear namespace failed: {e}")

        return len(local_keys)


# =============================================================================
# Global Cache Instance
# =============================================================================

cache = DistributedCache(namespace="tesslate")


# =============================================================================
# Decorator for Caching Function Results
# =============================================================================


def cached(key_prefix: str, ttl: int = 300):
    """
    Decorator to cache async function results.

    Args:
        key_prefix: Prefix for the cache key
        ttl: Time to live in seconds

    Usage:
        @cached("litellm_models", ttl=300)
        async def get_models():
            return await expensive_api_call()

    Note: This generates cache keys from the function name and key_prefix.
    For functions with arguments, use cache.get_or_set() directly
    with a key that includes the arguments.
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Simple cache key for parameterless functions
            cache_key = key_prefix

            return await cache.get_or_set(
                cache_key,
                lambda: func(*args, **kwargs),
                ttl,
            )

        return wrapper

    return decorator


# =============================================================================
# Specific Cache Utilities
# =============================================================================


async def get_cached_litellm_models() -> list | None:
    """
    Get LiteLLM models from cache.
    Used by marketplace router.
    """
    return await cache.get("litellm_models")


async def set_cached_litellm_models(models: list, ttl: int = 300):
    """
    Cache LiteLLM models.
    Used by marketplace router.
    """
    await cache.set("litellm_models", models, ttl)


async def invalidate_litellm_models():
    """
    Invalidate LiteLLM models cache.
    Call after model configuration changes.
    """
    await cache.delete("litellm_models")
