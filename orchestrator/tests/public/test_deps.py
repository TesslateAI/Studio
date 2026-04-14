"""Unit tests for public router dependencies (_deps.py)."""
from __future__ import annotations

import time
from uuid import uuid4

import pytest

from app.routers.public import _deps


def test_rate_limiter_allows_under_capacity():
    key_id = uuid4()
    _deps._BUCKETS.pop(key_id, None)
    for _ in range(5):
        allowed, retry = _deps._consume(key_id, cost=1.0, capacity=10, refill_per_sec=1.0)
        assert allowed is True
        assert retry == 0.0


def test_rate_limiter_rejects_over_capacity():
    key_id = uuid4()
    _deps._BUCKETS.pop(key_id, None)
    for _ in range(3):
        _deps._consume(key_id, cost=1.0, capacity=3, refill_per_sec=1.0)
    allowed, retry = _deps._consume(key_id, cost=1.0, capacity=3, refill_per_sec=1.0)
    assert allowed is False
    assert retry > 0.0


def test_rate_limiter_refills_over_time():
    key_id = uuid4()
    _deps._BUCKETS.pop(key_id, None)
    # Drain
    for _ in range(3):
        _deps._consume(key_id, cost=1.0, capacity=3, refill_per_sec=100.0)
    # Let it refill
    time.sleep(0.05)  # 0.05 * 100 = 5 tokens back
    allowed, _ = _deps._consume(key_id, cost=1.0, capacity=3, refill_per_sec=100.0)
    assert allowed is True


def test_rate_limiter_independent_per_key():
    a, b = uuid4(), uuid4()
    _deps._BUCKETS.pop(a, None)
    _deps._BUCKETS.pop(b, None)
    for _ in range(3):
        assert _deps._consume(a, cost=1.0, capacity=3, refill_per_sec=1.0)[0]
    # `a` is drained but `b` should be fresh
    assert _deps._consume(b, cost=1.0, capacity=3, refill_per_sec=1.0)[0] is True


def test_heavy_cost_blocks_small_bucket():
    key_id = uuid4()
    _deps._BUCKETS.pop(key_id, None)
    allowed, retry = _deps._consume(key_id, cost=100.0, capacity=10, refill_per_sec=1.0)
    assert allowed is False
    assert retry > 0


@pytest.mark.asyncio
async def test_audit_write_noop_without_team(monkeypatch):
    """audit_write should silently no-op for users with no default_team_id."""
    class _User:
        id = uuid4()
        default_team_id = None

    called = False

    async def _log_event(**_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "app.services.audit_service.log_event", _log_event
    )
    await _deps.audit_write(
        db=None,  # type: ignore[arg-type]
        user=_User(),  # type: ignore[arg-type]
        action="test.action",
        resource_type="test",
    )
    assert called is False
