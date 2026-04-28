"""Tests for the parallel-agent concurrency caps + enqueue rate limiter.

The service uses Redis ZSETs for slot tracking + sliding-window rate limit.
When Redis is unavailable (single-pod dev), the checks degrade to no-op —
that path is covered too.
"""

from __future__ import annotations

import pytest

from app.services import concurrency_limits as cl


class _FakeRedis:
    """Minimal Redis double backing ZSET + expire used by the service."""

    def __init__(self) -> None:
        self.zsets: dict[str, dict[str, float]] = {}

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        bucket = self.zsets.setdefault(key, {})
        added = 0
        for member, score in mapping.items():
            if member not in bucket:
                added += 1
            bucket[member] = score
        return added

    async def zrem(self, key: str, *members: str) -> int:
        bucket = self.zsets.get(key, {})
        removed = 0
        for m in members:
            if m in bucket:
                del bucket[m]
                removed += 1
        return removed

    async def zcard(self, key: str) -> int:
        return len(self.zsets.get(key, {}))

    async def zremrangebyscore(self, key: str, mn: str, mx: float) -> int:
        bucket = self.zsets.get(key, {})
        lo = float("-inf") if mn == "-inf" else float(mn)
        removed: list[str] = [m for m, s in bucket.items() if lo <= s <= mx]
        for m in removed:
            del bucket[m]
        return len(removed)

    async def expire(self, key: str, ttl: int) -> int:  # no-op for the fake
        return 1


@pytest.fixture(autouse=True)
def _patch_redis(monkeypatch):
    fake = _FakeRedis()

    async def _getter():
        return fake

    monkeypatch.setattr(cl, "get_redis_client", _getter)
    return fake


@pytest.mark.asyncio
async def test_reserve_then_release_round_trip():
    await cl.check_and_reserve_slot(user_id="u1", project_id="p1", task_id="t1")
    await cl.release_slot(user_id="u1", project_id="p1", task_id="t1")


@pytest.mark.asyncio
async def test_user_cap_blocks_over_limit(monkeypatch):
    monkeypatch.setattr(cl.settings, "user_max_concurrent_agents", 2)
    monkeypatch.setattr(cl.settings, "project_max_concurrent_agents", 100)
    monkeypatch.setattr(cl.settings, "user_enqueue_rate_per_10s", 100)

    await cl.check_and_reserve_slot("u1", "p1", "t1")
    await cl.check_and_reserve_slot("u1", "p1", "t2")
    with pytest.raises(cl.CapacityExceeded) as exc:
        await cl.check_and_reserve_slot("u1", "p1", "t3")
    assert exc.value.limit == 2

    # Freeing a slot lets the next enqueue through.
    await cl.release_slot("u1", "p1", "t1")
    await cl.check_and_reserve_slot("u1", "p1", "t3")


@pytest.mark.asyncio
async def test_project_cap_blocks_over_limit(monkeypatch):
    monkeypatch.setattr(cl.settings, "user_max_concurrent_agents", 100)
    monkeypatch.setattr(cl.settings, "project_max_concurrent_agents", 1)
    monkeypatch.setattr(cl.settings, "user_enqueue_rate_per_10s", 100)

    await cl.check_and_reserve_slot("u1", "p1", "t1")
    with pytest.raises(cl.CapacityExceeded):
        await cl.check_and_reserve_slot("u2", "p1", "t2")


@pytest.mark.asyncio
async def test_rate_limit_kicks_in(monkeypatch):
    monkeypatch.setattr(cl.settings, "user_max_concurrent_agents", 100)
    monkeypatch.setattr(cl.settings, "project_max_concurrent_agents", 100)
    monkeypatch.setattr(cl.settings, "user_enqueue_rate_per_10s", 2)

    await cl.check_and_reserve_slot("u1", "p1", "t1")
    await cl.check_and_reserve_slot("u1", "p1", "t2")
    with pytest.raises(cl.CapacityExceeded) as exc:
        await cl.check_and_reserve_slot("u1", "p1", "t3")
    assert "slow down" in exc.value.reason.lower()


@pytest.mark.asyncio
async def test_no_redis_is_non_blocking(monkeypatch):
    """When Redis is down, the service must not block enqueues."""

    async def _none():
        return None

    monkeypatch.setattr(cl, "get_redis_client", _none)
    # Should silently succeed.
    await cl.check_and_reserve_slot("u1", "p1", "t1")
    await cl.release_slot("u1", "p1", "t1")
