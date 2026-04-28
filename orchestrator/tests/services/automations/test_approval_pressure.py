"""Phase 2 — unit tests for ``services.automations.approval_pressure``.

The pressure cap is the safety-net for the unresumable approval path
(Phase 2 stopgap). Tests assert:

* ``compute_cap`` honors the floor (``max(2, n//4)``) and the env override.
* ``try_acquire_pressure_slot`` is atomic (Lua check-and-INCR), returns a
  token under cap, and ``None`` at cap.
* ``release_pressure_slot`` decrements and is idempotent against
  double-release.
* ``compute_jittered_backoff`` produces values within ±30% of each
  attempt's center window.
* ``schedule_deferred_retry`` enqueues with the right ARQ kwargs and
  bails at ``MAX_DEFER_ATTEMPTS``.

Redis is stubbed in-process — the Lua semantics are reimplemented in
Python so we exercise the cap-breach branch without needing a real
Redis instance.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

# Import the leaf module directly to avoid pulling the full
# ``app.services.automations`` package init chain (dispatcher imports
# the agent + tesslate-agent submodule, which is heavyweight). The
# pressure-cap module has zero in-package dependencies, so file-level
# import is safe and keeps these tests fast.
import importlib.util
import pathlib
import sys

_MOD_PATH = (
    pathlib.Path(__file__).resolve().parents[3]
    / "app"
    / "services"
    / "automations"
    / "approval_pressure.py"
)
_MOD_NAME = "approval_pressure_under_test"
_spec = importlib.util.spec_from_file_location(_MOD_NAME, _MOD_PATH)
assert _spec is not None and _spec.loader is not None
approval_pressure = importlib.util.module_from_spec(_spec)
# Register before exec so the @dataclass decorator can resolve the
# module via sys.modules during class-body processing (3.14 needs this).
sys.modules[_MOD_NAME] = approval_pressure
_spec.loader.exec_module(approval_pressure)


# ---------------------------------------------------------------------------
# In-process Redis fake (only the surface this module exercises).
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Minimal stand-in for ``redis.asyncio.Redis``.

    Implements the eval/decr/set/get surface that ``approval_pressure``
    actually calls. The Lua script is reimplemented in Python so we
    cover the atomic check-and-INCR semantics.
    """

    def __init__(self) -> None:
        self._kv: dict[str, int] = {}
        self.eval_calls: list[tuple[str, int, tuple[Any, ...]]] = []
        self.decr_calls: list[str] = []

    async def eval(self, script: str, numkeys: int, *args: Any) -> int:
        self.eval_calls.append((script, numkeys, args))
        # The module ships a single Lua script — the check-and-INCR.
        # Replicate its semantics in Python so cap-breach is testable
        # without a real Redis.
        key = args[0]
        cap = int(args[1])
        cur = int(self._kv.get(key, 0))
        if cur < cap:
            new_value = cur + 1
            self._kv[key] = new_value
            return new_value
        return -1

    async def decr(self, key: str) -> int:
        self.decr_calls.append(key)
        new_value = int(self._kv.get(key, 0)) - 1
        self._kv[key] = new_value
        return new_value

    async def set(self, key: str, value: Any) -> bool:
        self._kv[key] = int(value)
        return True

    async def get(self, key: str) -> str | None:
        if key not in self._kv:
            return None
        return str(self._kv[key])

    def current(self, key: str) -> int:
        return int(self._kv.get(key, 0))


# ---------------------------------------------------------------------------
# compute_cap
# ---------------------------------------------------------------------------


class TestComputeCap:
    def test_floor_of_2_on_tiny_pool(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(
            "AUTOMATION_APPROVAL_PRESSURE_CAP", raising=False
        )
        # 4 // 4 = 1, but the floor of 2 wins so the very first
        # escalation doesn't deadlock the cap.
        assert approval_pressure.compute_cap(arq_pool_size=4) == 2

    def test_quarter_pool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(
            "AUTOMATION_APPROVAL_PRESSURE_CAP", raising=False
        )
        assert approval_pressure.compute_cap(arq_pool_size=16) == 4
        assert approval_pressure.compute_cap(arq_pool_size=32) == 8
        assert approval_pressure.compute_cap(arq_pool_size=64) == 16

    def test_env_override_wins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUTOMATION_APPROVAL_PRESSURE_CAP", "12")
        # Override beats the computed value (would have been 4).
        assert approval_pressure.compute_cap(arq_pool_size=16) == 12

    def test_env_override_invalid_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUTOMATION_APPROVAL_PRESSURE_CAP", "not-a-number")
        # Falls back to the computed value, doesn't crash.
        assert approval_pressure.compute_cap(arq_pool_size=16) == 4

    def test_env_override_below_one_clamps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUTOMATION_APPROVAL_PRESSURE_CAP", "0")
        # 0 would deadlock every acquire; clamp to 1 (caller surface).
        assert approval_pressure.compute_cap(arq_pool_size=16) == 1

    def test_zero_pool_size_defensive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(
            "AUTOMATION_APPROVAL_PRESSURE_CAP", raising=False
        )
        # Misconfigured pool size shouldn't return 0 (which would
        # deadlock every escalation).
        assert approval_pressure.compute_cap(arq_pool_size=0) == 2


# ---------------------------------------------------------------------------
# try_acquire_pressure_slot
# ---------------------------------------------------------------------------


class TestTryAcquire:
    @pytest.mark.asyncio
    async def test_under_cap_returns_token_and_increments(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(
            "AUTOMATION_APPROVAL_PRESSURE_CAP", raising=False
        )
        fake = _FakeRedis()

        token = await approval_pressure.try_acquire_pressure_slot(
            arq_pool_size=16, redis_client=fake
        )

        assert token is not None
        assert token.pool_key == approval_pressure.POOL_KEY
        assert token.is_released() is False
        assert fake.current(approval_pressure.POOL_KEY) == 1
        assert len(fake.eval_calls) == 1

    @pytest.mark.asyncio
    async def test_at_cap_returns_none_no_increment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(
            "AUTOMATION_APPROVAL_PRESSURE_CAP", raising=False
        )
        fake = _FakeRedis()
        # cap for arq_pool_size=16 is 4; pre-fill to cap.
        fake._kv[approval_pressure.POOL_KEY] = 4

        token = await approval_pressure.try_acquire_pressure_slot(
            arq_pool_size=16, redis_client=fake
        )

        assert token is None
        # Counter must not have moved.
        assert fake.current(approval_pressure.POOL_KEY) == 4

    @pytest.mark.asyncio
    async def test_no_redis_issues_synthetic_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Desktop / no-Redis path: get_redis_client returns None, but
        # the caller still gets a token so its release path is symmetric.
        async def _no_redis() -> None:
            return None

        monkeypatch.setattr(
            approval_pressure, "_get_redis", _no_redis
        )

        token = await approval_pressure.try_acquire_pressure_slot(
            arq_pool_size=16
        )

        assert token is not None
        assert token.is_released() is False

    @pytest.mark.asyncio
    async def test_redis_failure_returns_token_no_block(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # If redis.eval blows up mid-acquire we prefer brief
        # over-subscription to blocking the user. The Phase 4 controller
        # sweep is responsible for reaping any stuck runs.
        class _BoomRedis(_FakeRedis):
            async def eval(self, *_a: Any, **_k: Any) -> int:
                raise RuntimeError("redis is having a bad day")

        token = await approval_pressure.try_acquire_pressure_slot(
            arq_pool_size=16, redis_client=_BoomRedis()
        )
        assert token is not None

    @pytest.mark.asyncio
    async def test_concurrent_acquires_serialize_correctly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The Lua reimplementation mirrors the real script's atomicity.
        # Five concurrent acquires on a cap-of-4 pool: 4 succeed, 1 fails.
        monkeypatch.delenv(
            "AUTOMATION_APPROVAL_PRESSURE_CAP", raising=False
        )
        fake = _FakeRedis()
        import asyncio

        results = await asyncio.gather(
            *(
                approval_pressure.try_acquire_pressure_slot(
                    arq_pool_size=16, redis_client=fake
                )
                for _ in range(5)
            )
        )

        granted = [r for r in results if r is not None]
        denied = [r for r in results if r is None]

        assert len(granted) == 4
        assert len(denied) == 1
        assert fake.current(approval_pressure.POOL_KEY) == 4


# ---------------------------------------------------------------------------
# release_pressure_slot
# ---------------------------------------------------------------------------


class TestRelease:
    @pytest.mark.asyncio
    async def test_release_decrements(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(
            "AUTOMATION_APPROVAL_PRESSURE_CAP", raising=False
        )
        fake = _FakeRedis()

        token = await approval_pressure.try_acquire_pressure_slot(
            arq_pool_size=16, redis_client=fake
        )
        assert token is not None
        assert fake.current(approval_pressure.POOL_KEY) == 1

        await approval_pressure.release_pressure_slot(
            token, redis_client=fake
        )

        assert fake.current(approval_pressure.POOL_KEY) == 0
        assert token.is_released() is True
        assert fake.decr_calls == [approval_pressure.POOL_KEY]

    @pytest.mark.asyncio
    async def test_double_release_is_idempotent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Defensive: callers may release in a finally block AND in a
        # success path. Second release must be a no-op (no extra DECR).
        monkeypatch.delenv(
            "AUTOMATION_APPROVAL_PRESSURE_CAP", raising=False
        )
        fake = _FakeRedis()

        token = await approval_pressure.try_acquire_pressure_slot(
            arq_pool_size=16, redis_client=fake
        )
        assert token is not None

        await approval_pressure.release_pressure_slot(
            token, redis_client=fake
        )
        await approval_pressure.release_pressure_slot(
            token, redis_client=fake
        )

        assert fake.current(approval_pressure.POOL_KEY) == 0
        # Only one DECR — the second call short-circuited.
        assert len(fake.decr_calls) == 1

    @pytest.mark.asyncio
    async def test_release_resets_negative_counter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # If the counter has been corrupted (e.g. an external reset),
        # a DECR can land at -1. We log loudly and reset to 0 so the
        # leak surfaces in monitoring instead of silently corrupting
        # future acquires.
        fake = _FakeRedis()
        fake._kv[approval_pressure.POOL_KEY] = 0

        from datetime import UTC, datetime

        token = approval_pressure.PressureToken(
            pool_key=approval_pressure.POOL_KEY,
            acquired_at=datetime.now(tz=UTC),
            _released=[False],
        )
        await approval_pressure.release_pressure_slot(
            token, redis_client=fake
        )

        # DECR took us to -1; the reset path landed us at 0.
        assert fake.current(approval_pressure.POOL_KEY) == 0


# ---------------------------------------------------------------------------
# compute_jittered_backoff
# ---------------------------------------------------------------------------


class TestJitteredBackoff:
    def test_attempt_0_window_5min(self) -> None:
        # 5min ± 30% → [3.5min, 6.5min]
        for _ in range(50):
            d = approval_pressure.compute_jittered_backoff(0)
            assert isinstance(d, timedelta)
            seconds = d.total_seconds()
            assert 3.5 * 60 <= seconds <= 6.5 * 60

    def test_attempt_1_window_15min(self) -> None:
        # 15min ± 30% → [10.5min, 19.5min]
        for _ in range(50):
            d = approval_pressure.compute_jittered_backoff(1)
            seconds = d.total_seconds()
            assert 10.5 * 60 <= seconds <= 19.5 * 60

    def test_attempt_2_window_45min(self) -> None:
        # 45min ± 30% → [31.5min, 58.5min]
        for _ in range(50):
            d = approval_pressure.compute_jittered_backoff(2)
            seconds = d.total_seconds()
            assert 31.5 * 60 <= seconds <= 58.5 * 60

    def test_attempt_3_raises(self) -> None:
        with pytest.raises(ValueError):
            approval_pressure.compute_jittered_backoff(3)

    def test_jitter_actually_jitters(self) -> None:
        # Sanity: across 50 samples we should see at least 10 distinct
        # values (uniform random, not a fixed multiple).
        samples = {
            approval_pressure.compute_jittered_backoff(0).total_seconds()
            for _ in range(50)
        }
        assert len(samples) > 10


# ---------------------------------------------------------------------------
# schedule_deferred_retry
# ---------------------------------------------------------------------------


class TestScheduleDeferredRetry:
    @pytest.mark.asyncio
    async def test_first_retry_enqueues_with_defer_kwargs(self) -> None:
        pool = AsyncMock()
        pool.enqueue_job = AsyncMock(return_value=None)
        automation_id = uuid4()
        event_id = uuid4()

        ok = await approval_pressure.schedule_deferred_retry(
            pool=pool,
            automation_id=automation_id,
            event_id=event_id,
            worker_id="worker-1",
            attempt=0,
        )

        assert ok is True
        assert pool.enqueue_job.await_count == 1
        args, kwargs = pool.enqueue_job.call_args
        assert args[0] == "dispatch_automation_task"
        assert args[1] == str(automation_id)
        assert args[2] == str(event_id)
        # Worker id chains so a subsequent dispatch can trace the lineage.
        assert args[3] == "worker-1-retry-1"
        # ARQ-native kwargs.
        assert isinstance(kwargs["_defer_by"], timedelta)
        assert kwargs["_job_id"] == f"{event_id}-retry-1"
        # First-window backoff lands inside ±30% of 5min.
        seconds = kwargs["_defer_by"].total_seconds()
        assert 3.5 * 60 <= seconds <= 6.5 * 60

    @pytest.mark.asyncio
    async def test_second_retry_lands_in_15min_window(self) -> None:
        pool = AsyncMock()
        pool.enqueue_job = AsyncMock(return_value=None)

        ok = await approval_pressure.schedule_deferred_retry(
            pool=pool,
            automation_id=uuid4(),
            event_id=uuid4(),
            worker_id="w",
            attempt=1,
        )

        assert ok is True
        kwargs = pool.enqueue_job.call_args.kwargs
        seconds = kwargs["_defer_by"].total_seconds()
        assert 10.5 * 60 <= seconds <= 19.5 * 60

    @pytest.mark.asyncio
    async def test_third_retry_lands_in_45min_window(self) -> None:
        pool = AsyncMock()
        pool.enqueue_job = AsyncMock(return_value=None)

        ok = await approval_pressure.schedule_deferred_retry(
            pool=pool,
            automation_id=uuid4(),
            event_id=uuid4(),
            worker_id="w",
            attempt=2,
        )

        assert ok is True
        kwargs = pool.enqueue_job.call_args.kwargs
        seconds = kwargs["_defer_by"].total_seconds()
        assert 31.5 * 60 <= seconds <= 58.5 * 60

    @pytest.mark.asyncio
    async def test_attempt_at_max_returns_false_no_enqueue(self) -> None:
        pool = AsyncMock()
        pool.enqueue_job = AsyncMock(return_value=None)

        ok = await approval_pressure.schedule_deferred_retry(
            pool=pool,
            automation_id=uuid4(),
            event_id=uuid4(),
            worker_id="w",
            attempt=approval_pressure.MAX_DEFER_ATTEMPTS,
        )

        assert ok is False
        pool.enqueue_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_enqueue_failure_returns_false(self) -> None:
        # ARQ enqueue can transiently fail; the dispatcher must learn
        # we failed to defer so it can fail the run cleanly instead of
        # silently dropping the retry.
        pool = AsyncMock()
        pool.enqueue_job = AsyncMock(
            side_effect=RuntimeError("redis pool down")
        )

        ok = await approval_pressure.schedule_deferred_retry(
            pool=pool,
            automation_id=uuid4(),
            event_id=uuid4(),
            worker_id="w",
            attempt=0,
        )

        assert ok is False


# ---------------------------------------------------------------------------
# Module-level constants — guard against accidental mutation
# ---------------------------------------------------------------------------


class TestModuleSurface:
    def test_pool_key_is_canonical(self) -> None:
        # The plan calls out this exact key shape; renaming it would
        # silently fork the counter from a previously-deployed pool.
        assert approval_pressure.POOL_KEY == "tesslate:approvals:inflight:pool"

    def test_max_defer_attempts(self) -> None:
        assert approval_pressure.MAX_DEFER_ATTEMPTS == 3

    def test_lua_script_shape(self) -> None:
        # The Lua script must (a) GET, (b) compare against ARGV cap,
        # (c) INCR on win, (d) return -1 on cap-breach. Defensive
        # check so a refactor doesn't accidentally change semantics.
        s = approval_pressure.LUA_TRY_INCR
        assert "redis.call('GET'" in s
        assert "redis.call('INCR'" in s
        assert "return -1" in s
