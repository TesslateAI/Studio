"""Periodic recovery sweep for orphaned ``automation_events`` (Phase 4).

Moves the recovery loop out of the gateway and into the controller.
Backed by :func:`app.services.apps.schedule_triggers.process_trigger_events_batch`
which already implements the row claim + retry semantics; this module
just wraps it in a leader-side loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


_DRAIN_INTERVAL_SECONDS = 30


async def run_loop(
    *,
    db_factory: Callable[[], Any],
    arq_pool: Any | None,
    shutdown_event: asyncio.Event,
    interval_seconds: int = _DRAIN_INTERVAL_SECONDS,
) -> None:
    """Drain orphaned events until shutdown.

    Wraps :func:`process_trigger_events_batch` (which sets up its own
    sessions and grace cutoff). The drain function tolerates being
    invoked with a worker context dict OR ``None`` — we pass a small
    dict carrying the ARQ pool so the drain can enqueue without
    re-creating it.
    """
    logger.info("[DRAIN] starting (interval=%ds)", interval_seconds)

    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(
                shutdown_event.wait(), timeout=interval_seconds
            )
            return
        except TimeoutError:
            pass

        try:
            await drain_once(arq_pool=arq_pool)
        except Exception:
            logger.exception("[DRAIN] tick failed")


async def drain_once(*, arq_pool: Any | None) -> dict[str, int]:
    """Single drain pass. Returns ``{processed, failed, skipped}``."""
    from ..apps.schedule_triggers import process_trigger_events_batch

    ctx: dict[str, Any] = {}
    if arq_pool is not None:
        # ``schedule_triggers`` looks up ``ctx['redis']`` for its pool.
        # ARQ's worker ctx uses the same key.
        ctx["redis"] = arq_pool

    return await process_trigger_events_batch(ctx)


__all__ = ["run_loop", "drain_once"]
