"""Approval-pressure cap (Phase 2 stopgap).

Hard cap on the number of dispatcher workers that may simultaneously hold an
ARQ slot waiting on a human approval response. Phase 6 ships full
agent-state checkpointing (the real fix); Wave 2A's checkpoint covers the
*resumable* subset (every tool annotated ``state_serializable=True``). This
module is the safety-net for the genuinely *unresumable* subset — a tool
mid-call with non-serializable state where the worker would otherwise have
to block-and-wait on a Redis pubsub for the human's reply.

Design (from the plan, §"Worker-suspension backpressure"):

* **Per-pool** cap, **not per-worker** — slots are fungible, and per-worker
  keys leak on scale-down (ARQ worker IDs are not stable across deploys).
* Single Redis key ``tesslate:approvals:inflight:pool`` with a Lua
  ``check-and-INCR`` script for atomic slot acquisition. No race window
  between the read and the write.
* Cap = ``max(2, ARQ_POOL_SIZE // 4)`` by default; overridable by
  ``AUTOMATION_APPROVAL_PRESSURE_CAP`` for ops to tune without a code push.
* No TTL on the pool key — counter is reset by explicit DECRs only.
  (TTL would silently mask leaks; explicit release surfaces them in logs.)
* Jittered backoff on cap-breach: 5min ± 30%, 15min ± 30%, 45min ± 30%,
  max 3 attempts. Uniform random within each window — fixed multiples
  turn a 9am collision into a sustained sync pattern.

Integration (in ``dispatcher.py``):

The cap is wired as a **defensive check** — it fires only on the genuinely
unresumable path (where Wave 2A's ``checkpoint.serialize_checkpoint``
either raises or returns ``resume_strategy='restart_from_checkpoint'``
with no usable snapshot). In normal operation the dispatcher uses the
checkpoint+resume flow and never asks the cap for a slot. If checkpoint
construction fails and we are about to fall back to block-and-wait, the
cap rate-limits the failure mode and tells us via metrics that the
checkpoint surface has a regression.

The slot is held only for the *milliseconds* it takes to write the
approval-request row. The actual long human-wait happens with the slot
already released.
"""

from __future__ import annotations

import logging
import os
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:  # pragma: no cover - typing only
    from arq.connections import ArqRedis

logger = logging.getLogger(__name__)


__all__ = [
    "POOL_KEY",
    "MAX_DEFER_ATTEMPTS",
    "ApprovalCapacityExceeded",
    "PressureToken",
    "compute_cap",
    "compute_jittered_backoff",
    "release_pressure_slot",
    "schedule_deferred_retry",
    "try_acquire_pressure_slot",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

POOL_KEY = "tesslate:approvals:inflight:pool"
"""Single Redis key tracking how many runs are currently mid-acquisition of an
unresumable approval slot. Per-pool counter — not per-worker."""

MAX_DEFER_ATTEMPTS = 3
"""Hard ceiling on the deferred-retry chain. After three jittered retries the
run is failed with ``approval_capacity_exceeded_max_retries``."""

# Lua script: atomic check-and-INCR. The whole script runs single-threaded
# inside Redis so there's no read/write race. Returns the new value on
# success, ``-1`` if the cap would be breached.
LUA_TRY_INCR = """
local key = KEYS[1]
local cap = tonumber(ARGV[1])
local cur = tonumber(redis.call('GET', key) or '0')
if cur < cap then
  return redis.call('INCR', key)
end
return -1
"""


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class ApprovalCapacityExceeded(RuntimeError):
    """Raised when the cap is breached and no defer is possible.

    Callers that want the soft path should call ``try_acquire_pressure_slot``
    directly and inspect the ``None`` return value. This exception exists
    so that helper layers (e.g., a future ContractGate fallback) can raise
    instead of returning sentinels.
    """


@dataclass(frozen=True)
class PressureToken:
    """Receipt for a successful slot acquisition.

    The caller MUST call :func:`release_pressure_slot` exactly once. The
    token is idempotent against double-release — the second call is a
    no-op so finally-blocks can be defensive without leaking decrements.
    """

    pool_key: str
    acquired_at: datetime
    # Mutable flag carried as a single-element list so the dataclass can
    # stay ``frozen=True`` (immutable hash) while still recording whether
    # the token has been released. Tests assert both shapes.
    _released: list[bool]

    def is_released(self) -> bool:
        return bool(self._released and self._released[0])


# ---------------------------------------------------------------------------
# Cap computation
# ---------------------------------------------------------------------------


def compute_cap(arq_pool_size: int) -> int:
    """Compute the per-pool cap.

    Default: ``max(2, arq_pool_size // 4)``. The ``2`` floor keeps the
    cap meaningful on tiny pools (a 4-slot pool still gets cap=2 instead
    of cap=1, which would deadlock the very first escalation).

    Override via the ``AUTOMATION_APPROVAL_PRESSURE_CAP`` env var. Ops
    can tune without a code push when, e.g., a long-running approval
    workflow temporarily needs more headroom.
    """
    env_override = os.environ.get("AUTOMATION_APPROVAL_PRESSURE_CAP")
    if env_override:
        try:
            cap = int(env_override)
        except ValueError:
            logger.warning(
                "approval_pressure: invalid AUTOMATION_APPROVAL_PRESSURE_CAP=%r, "
                "falling back to computed cap",
                env_override,
            )
        else:
            if cap < 1:
                logger.warning(
                    "approval_pressure: AUTOMATION_APPROVAL_PRESSURE_CAP=%d < 1; "
                    "clamping to 1",
                    cap,
                )
                return 1
            return cap

    if arq_pool_size <= 0:
        # Defensive: a misconfigured pool size of 0 would yield cap=2 from
        # the floor, which is correct (we want at least one approval slot
        # available in any reasonable deployment).
        return 2
    return max(2, arq_pool_size // 4)


# ---------------------------------------------------------------------------
# Slot acquire / release
# ---------------------------------------------------------------------------


async def _get_redis() -> Any | None:
    """Return the process-wide redis client, or ``None`` on desktop/no-redis.

    Indirection so tests can monkeypatch a single seam without reaching
    into ``cache_service`` internals.
    """
    from ..cache_service import get_redis_client

    return await get_redis_client()


async def try_acquire_pressure_slot(
    *,
    arq_pool_size: int,
    redis_client: Any | None = None,
) -> PressureToken | None:
    """Atomically acquire one approval-pressure slot.

    Returns a :class:`PressureToken` on success (caller MUST release).
    Returns ``None`` when the cap would be breached — caller should
    schedule a deferred retry via :func:`schedule_deferred_retry`.

    Returns a token unconditionally when Redis is unavailable
    (desktop / no-Redis mode). The cap is a *cloud-pool* primitive; on
    desktop the worker pool is local and the in-process queue handles
    contention via its own bounded executor.

    Args:
        arq_pool_size: The configured ARQ worker pool size for this
            deployment. Used to compute the cap. Pass
            ``settings.worker_max_jobs * worker_replicas`` if you have
            a horizontal-scale story; otherwise ``settings.worker_max_jobs``
            is the single-replica answer.
        redis_client: Optional injected client (tests). Production callers
            leave this ``None`` and we resolve via :func:`_get_redis`.
    """
    redis = redis_client if redis_client is not None else await _get_redis()
    if redis is None:
        # Desktop / no-Redis: no shared pool to contend on. Issue a
        # synthetic token so the caller's release path is symmetric.
        logger.debug(
            "approval_pressure.try_acquire: redis unavailable, issuing "
            "synthetic token (desktop/no-redis mode)"
        )
        return PressureToken(
            pool_key=POOL_KEY,
            acquired_at=datetime.now(tz=UTC),
            _released=[False],
        )

    cap = compute_cap(arq_pool_size)
    try:
        result = await redis.eval(LUA_TRY_INCR, 1, POOL_KEY, str(cap))
    except Exception:
        # Redis failure mid-acquire: log and let the caller proceed
        # without a slot. We prefer a brief over-subscription to
        # blocking the user when Redis is flaky — the Phase 4 controller
        # sweep will reap any stuck runs.
        logger.exception(
            "approval_pressure.try_acquire: redis.eval failed; "
            "proceeding without slot accounting"
        )
        return PressureToken(
            pool_key=POOL_KEY,
            acquired_at=datetime.now(tz=UTC),
            _released=[False],
        )

    # Redis returns int (or bytes-coerced int depending on client). The
    # Lua script returns -1 on cap breach, otherwise the new counter value.
    try:
        value = int(result)
    except (TypeError, ValueError):
        logger.warning(
            "approval_pressure.try_acquire: unexpected eval result %r; "
            "treating as cap-breach",
            result,
        )
        return None

    if value < 0:
        logger.info(
            "approval_pressure.try_acquire: cap breached (cap=%d) — caller "
            "should defer",
            cap,
        )
        return None

    logger.debug(
        "approval_pressure.try_acquire: acquired slot %d/%d", value, cap
    )
    return PressureToken(
        pool_key=POOL_KEY,
        acquired_at=datetime.now(tz=UTC),
        _released=[False],
    )


async def release_pressure_slot(
    token: PressureToken,
    *,
    redis_client: Any | None = None,
) -> None:
    """Release one slot. Idempotent against double-release.

    Safe to call from a ``finally`` block — a missing/expired counter
    or a redis hiccup is logged but never raised. The pool key has no
    TTL by design, so DECR cannot under-flow into garbage; if the
    counter is already 0 (e.g., after a manual reset) the redis client
    just returns -1, which we ignore.
    """
    if token.is_released():
        logger.debug("approval_pressure.release: token already released, no-op")
        return

    # Mark first so a concurrent release doesn't double-DECR. The list
    # mutation is in-place on the frozen dataclass's _released slot.
    token._released[0] = True

    redis = redis_client if redis_client is not None else await _get_redis()
    if redis is None:
        logger.debug(
            "approval_pressure.release: redis unavailable; nothing to DECR"
        )
        return

    try:
        new_value = await redis.decr(token.pool_key)
    except Exception:
        logger.exception(
            "approval_pressure.release: redis.decr failed for key=%s",
            token.pool_key,
        )
        return

    # Defensive: if we ever go negative the cap accounting is broken
    # somewhere upstream. Reset to 0 and log loudly so the leak surfaces
    # in monitoring instead of silently corrupting future acquires.
    try:
        if int(new_value) < 0:
            logger.warning(
                "approval_pressure.release: pool counter went negative (%s); "
                "resetting to 0",
                new_value,
            )
            try:
                await redis.set(token.pool_key, 0)
            except Exception:  # pragma: no cover - defensive nested
                logger.exception(
                    "approval_pressure.release: failed to reset negative "
                    "counter for %s",
                    token.pool_key,
                )
    except (TypeError, ValueError):
        logger.debug(
            "approval_pressure.release: non-numeric DECR result %r", new_value
        )


# ---------------------------------------------------------------------------
# Backoff + deferred retry
# ---------------------------------------------------------------------------


def compute_jittered_backoff(attempt: int) -> timedelta:
    """Return the delay for the ``attempt``-th deferred retry.

    Windows: 5min ± 30%, 15min ± 30%, 45min ± 30%. Uniform random
    within each window so a thundering-herd 9am collision spreads
    across the window instead of re-colliding at 9:05/9:15/9:45.

    ``attempt`` is the number of retries already taken — the *first*
    deferred retry passes ``attempt=0``.
    """
    if attempt == 0:
        center = timedelta(minutes=5)
    elif attempt == 1:
        center = timedelta(minutes=15)
    elif attempt == 2:
        center = timedelta(minutes=45)
    else:
        raise ValueError(
            f"compute_jittered_backoff: max attempts exceeded (got {attempt}, "
            f"max {MAX_DEFER_ATTEMPTS - 1})"
        )

    jitter_factor = random.uniform(0.7, 1.3)
    return timedelta(seconds=center.total_seconds() * jitter_factor)


async def schedule_deferred_retry(
    *,
    pool: "ArqRedis | Any",
    automation_id: UUID,
    event_id: UUID,
    worker_id: str,
    attempt: int,
) -> bool:
    """Enqueue a delayed ``dispatch_automation_task`` for this run.

    Returns ``True`` if the deferred job was enqueued, ``False`` when
    ``attempt`` would exceed :data:`MAX_DEFER_ATTEMPTS`. The caller is
    responsible for marking the run ``failed`` on a ``False`` return.

    The deferred job ID is deterministic
    (``"{event_id}-retry-{attempt+1}"``) so a duplicate dispatcher call
    that races into the same defer point won't enqueue twice — ARQ
    de-dupes on ``_job_id``.
    """
    if attempt >= MAX_DEFER_ATTEMPTS:
        logger.info(
            "approval_pressure.schedule_deferred_retry: max attempts reached "
            "(%d); refusing to enqueue automation=%s event=%s",
            attempt,
            automation_id,
            event_id,
        )
        return False

    backoff = compute_jittered_backoff(attempt)
    job_id = f"{event_id}-retry-{attempt + 1}"
    next_worker = f"{worker_id}-retry-{attempt + 1}"

    try:
        await pool.enqueue_job(
            "dispatch_automation_task",
            str(automation_id),
            str(event_id),
            next_worker,
            _defer_by=backoff,
            _job_id=job_id,
        )
    except Exception:
        logger.exception(
            "approval_pressure.schedule_deferred_retry: enqueue_job failed "
            "for automation=%s event=%s attempt=%d",
            automation_id,
            event_id,
            attempt,
        )
        return False

    logger.info(
        "approval_pressure.schedule_deferred_retry: deferred automation=%s "
        "event=%s attempt=%d delay=%.1fs job_id=%s",
        automation_id,
        event_id,
        attempt + 1,
        backoff.total_seconds(),
        job_id,
    )
    return True
