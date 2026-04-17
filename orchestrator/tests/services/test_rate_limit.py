"""Unit tests for the Redis-backed rate limiter (in-process fallback path).

These tests force the fallback by ensuring ``get_redis_client`` returns
``None``. The fallback shares the same accounting semantics as the Redis
path, so verifying it covers the user-visible contract.
"""

from __future__ import annotations

import pytest

from app.services import rate_limit
from app.services.rate_limit import RedisTokenBucket


@pytest.fixture(autouse=True)
def _force_fallback(monkeypatch):
    """Force the fallback path by stubbing the Redis factory to return None."""

    async def _none():
        return None

    # cache_service is imported lazily inside check_and_consume.
    from app.services import cache_service

    monkeypatch.setattr(cache_service, "get_redis_client", _none)
    rate_limit._reset_fallback_for_tests()
    yield
    rate_limit._reset_fallback_for_tests()


@pytest.mark.asyncio
async def test_burst_cap_allows_then_rejects():
    bucket = RedisTokenBucket()
    for i in range(10):
        allowed, remaining, reset = await bucket.check_and_consume(
            "reveal_secret_burst",
            "user-a",
            capacity=10,
            window_seconds=300,
        )
        assert allowed, f"call {i + 1} unexpectedly rejected"
        assert remaining == 10 - (i + 1)
        assert reset >= 1

    allowed, remaining, reset = await bucket.check_and_consume(
        "reveal_secret_burst",
        "user-a",
        capacity=10,
        window_seconds=300,
    )
    assert not allowed
    assert remaining == 0
    assert reset >= 1


@pytest.mark.asyncio
async def test_window_reset_clears_counter(monkeypatch):
    bucket = RedisTokenBucket()
    # Use a small window so we can simulate rollover.
    base_now = 1_000_000.0

    monkeypatch.setattr(rate_limit.time, "time", lambda: base_now)
    for _ in range(3):
        allowed, _, _ = await bucket.check_and_consume(
            "scope-x", "user-b", capacity=3, window_seconds=10
        )
        assert allowed
    allowed, _, _ = await bucket.check_and_consume(
        "scope-x", "user-b", capacity=3, window_seconds=10
    )
    assert not allowed

    # Advance well past the window boundary.
    monkeypatch.setattr(rate_limit.time, "time", lambda: base_now + 25.0)
    allowed, remaining, _ = await bucket.check_and_consume(
        "scope-x", "user-b", capacity=3, window_seconds=10
    )
    assert allowed, "counter should reset after window expiry"
    assert remaining == 2


@pytest.mark.asyncio
async def test_independent_subjects_have_independent_buckets():
    bucket = RedisTokenBucket()
    # Exhaust user-c.
    for _ in range(2):
        allowed, _, _ = await bucket.check_and_consume(
            "scope-y", "user-c", capacity=2, window_seconds=300
        )
        assert allowed
    allowed, _, _ = await bucket.check_and_consume(
        "scope-y", "user-c", capacity=2, window_seconds=300
    )
    assert not allowed

    # user-d should still have full quota.
    allowed, remaining, _ = await bucket.check_and_consume(
        "scope-y", "user-d", capacity=2, window_seconds=300
    )
    assert allowed
    assert remaining == 1
