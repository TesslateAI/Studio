"""Simple per-process circuit breaker for the AST client.

State machine: CLOSED → (N failures) → OPEN → (T seconds elapsed) → HALF_OPEN
  HALF_OPEN → success → CLOSED
  HALF_OPEN → failure → OPEN (reset timer)

Not distributed. Each backend replica keeps its own view. Blast radius of
disagreement is "one backend pod returns 503 for a few seconds while
others succeed" — the frontend retries design ops, which may land on a
different backend pod and succeed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import StrEnum

logger = logging.getLogger(__name__)


class CircuitOpenError(RuntimeError):
    """Raised when the circuit is open and a call is short-circuited."""


class _State(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int,
        reset_seconds: float,
        name: str = "circuit",
    ) -> None:
        self._name = name
        self._threshold = max(1, failure_threshold)
        self._reset = max(1.0, float(reset_seconds))
        self._failures = 0
        self._opened_at: float | None = None
        self._state = _State.CLOSED
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        return self._state.value

    async def _transition_if_elapsed(self) -> None:
        if (
            self._state is _State.OPEN
            and self._opened_at is not None
            and (time.monotonic() - self._opened_at) >= self._reset
        ):
            self._state = _State.HALF_OPEN
            logger.info("[%s] circuit half-open — probing", self._name)

    async def allow(self) -> None:
        """Raise CircuitOpenError if the circuit is currently open.

        Half-open lets exactly one probe through; subsequent calls arriving
        while the probe is in flight are rejected to avoid thundering herd.
        """
        async with self._lock:
            await self._transition_if_elapsed()
            if self._state is _State.OPEN:
                raise CircuitOpenError(
                    f"{self._name} open: reject for "
                    f"{self._reset - (time.monotonic() - (self._opened_at or 0)):.1f}s more"
                )
            if self._state is _State.HALF_OPEN:
                # Let one probe through; move back to OPEN so other
                # concurrent callers bounce until the probe resolves.
                self._state = _State.OPEN
                self._opened_at = time.monotonic()

    async def record_success(self) -> None:
        async with self._lock:
            if self._state is not _State.CLOSED:
                logger.info("[%s] circuit closed — success", self._name)
            self._state = _State.CLOSED
            self._failures = 0
            self._opened_at = None

    async def record_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            if self._failures >= self._threshold and self._state is not _State.OPEN:
                self._state = _State.OPEN
                self._opened_at = time.monotonic()
                logger.warning(
                    "[%s] circuit opened after %d consecutive failures",
                    self._name,
                    self._failures,
                )
