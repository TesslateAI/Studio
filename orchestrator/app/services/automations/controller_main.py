"""Controller-plane supervisor (Phase 4).

The supervisor owns the leader-election loop and, while leader, runs the
controller's child loops as a single :func:`asyncio.gather` tree:

* :func:`cron_producer.run_loop` — claims due cron triggers
* :func:`sweep_on_acquire.sweep_once` — one-shot at promote
* :func:`missed_event_drain.run_loop` — recovery sweep
* :func:`intents.reconciler.run_loop` — applies pending intents

Lease lifecycle
---------------
The supervisor calls :meth:`Lease.acquire` with TTL=60s. While leader,
it renews every 20s. If renewal returns ``False`` the supervisor cancels
all child tasks and reverts to the standby loop, where it sleeps for a
random interval before trying to re-acquire.

Cancellation contract
---------------------
Child loops MUST be ``CancelledError``-safe. The supervisor cancels and
``await``s their cleanup; loops that swallow CancelledError will stall
fail-over. See each loop module for the contract.

Entrypoint
----------
For Phase 4 this module is invoked as
``python -m app.services.automations.controller_main`` from the dedicated
``automations-controller`` Deployment (or — in single-process docker /
desktop modes — co-launched from the orchestrator's startup hook). The
top-level wiring lands in a follow-up commit so the file is not yet
auto-launched anywhere.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import signal
import socket
import uuid
from typing import Any, Callable, Optional

from .lease import Lease, LeaseToken, get_lease_backend

logger = logging.getLogger(__name__)


_LEASE_NAME = "controller"
_LEASE_TTL_SECONDS = 60
_RENEW_INTERVAL_SECONDS = 20
_STANDBY_BASE_SLEEP_SECONDS = 5
_STANDBY_MAX_SLEEP_SECONDS = 15


def _make_holder_id() -> str:
    """Build a stable-but-unique holder id for diagnostics.

    Format: ``<hostname>:<pid>:<short-uuid>``. Hostname + pid lets ops
    identify the pod from ``kubectl get leases``; the suffix breaks ties
    when a pod restarts inside the same TTL window.
    """
    host = os.environ.get("HOSTNAME") or socket.gethostname()
    return f"{host}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


async def run_controller(
    lease_backend: Optional[Lease] = None,
    db_factory: Optional[Callable[[], Any]] = None,
    arq_pool: Any | None = None,
    *,
    holder_id: Optional[str] = None,
    lease_name: str = _LEASE_NAME,
    ttl_seconds: int = _LEASE_TTL_SECONDS,
    renew_interval_seconds: int = _RENEW_INTERVAL_SECONDS,
) -> None:
    """Run the controller supervisor until SIGTERM / SIGINT.

    Parameters
    ----------
    lease_backend:
        Lease implementation. Defaults to
        :func:`get_lease_backend` (env-driven).
    db_factory:
        Async session factory. Defaults to
        ``app.database.AsyncSessionLocal``.
    arq_pool:
        ARQ pool used to enqueue ``dispatch_automation_task`` after
        cron / drain commits. ``None`` is allowed in desktop mode
        where the local task queue is used instead.
    holder_id:
        Unique identifier for this supervisor instance.
    """
    if lease_backend is None:
        lease_backend = get_lease_backend()

    if db_factory is None:
        from app.database import AsyncSessionLocal

        db_factory = AsyncSessionLocal

    if holder_id is None:
        holder_id = _make_holder_id()

    shutdown_event = asyncio.Event()

    def _on_signal(_signum: int, _frame: Any) -> None:
        logger.info("[CONTROLLER] received signal, initiating shutdown")
        # asyncio.Event.set is thread-safe per-event-loop; signal handlers
        # run in the main thread for asyncio so this is fine.
        try:
            asyncio.get_event_loop().call_soon_threadsafe(shutdown_event.set)
        except RuntimeError:
            shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            # Not on the main thread — supervisor is being run from a
            # test loop. Skip; the test owns the cancellation.
            pass

    logger.info(
        "[CONTROLLER] supervisor starting holder=%s lease=%s ttl=%ds",
        holder_id,
        lease_name,
        ttl_seconds,
    )

    while not shutdown_event.is_set():
        token = await lease_backend.acquire(lease_name, holder_id, ttl_seconds)
        if token is None:
            sleep_for = random.uniform(
                _STANDBY_BASE_SLEEP_SECONDS, _STANDBY_MAX_SLEEP_SECONDS
            )
            logger.debug(
                "[CONTROLLER] standby — failed to acquire lease, sleeping %.1fs",
                sleep_for,
            )
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=sleep_for)
            except TimeoutError:
                pass
            continue

        logger.info(
            "[CONTROLLER] acquired lease term=%d expires_at=%s",
            token.term,
            token.expires_at.isoformat(),
        )

        await _run_as_leader(
            lease_backend=lease_backend,
            token=token,
            db_factory=db_factory,
            arq_pool=arq_pool,
            renew_interval_seconds=renew_interval_seconds,
            shutdown_event=shutdown_event,
        )

    logger.info("[CONTROLLER] supervisor shut down cleanly")


async def _run_as_leader(
    *,
    lease_backend: Lease,
    token: LeaseToken,
    db_factory: Callable[[], Any],
    arq_pool: Any | None,
    renew_interval_seconds: int,
    shutdown_event: asyncio.Event,
) -> None:
    """Run all child loops while we hold the lease.

    Returns when either the lease is lost (renewal failure) or shutdown
    is requested. Cancels and awaits all child tasks before returning so
    the caller can cleanly retry acquire.
    """
    # Holder for the live token (renew returns a new token each time).
    current_token = token
    lease_lost = asyncio.Event()

    def _current_term() -> int:
        return current_token.term

    # Lazy imports keep test surface small.
    from . import cron_producer, missed_event_drain, sweep_on_acquire
    from .intents import reconciler as intents_reconciler

    # One-shot sweep at promote — flush any rows stuck queued during
    # the prior leader's failure window.
    try:
        await sweep_on_acquire.sweep_once(
            db_factory=db_factory, arq_pool=arq_pool, current_term=_current_term()
        )
    except Exception:
        logger.exception("[CONTROLLER] sweep_on_acquire failed; continuing")

    children = [
        asyncio.create_task(
            cron_producer.run_loop(
                db_factory=db_factory,
                arq_pool=arq_pool,
                lease_backend=lease_backend,
                token_provider=lambda: current_token,
                shutdown_event=lease_lost,
            ),
            name="controller.cron_producer",
        ),
        asyncio.create_task(
            missed_event_drain.run_loop(
                db_factory=db_factory,
                arq_pool=arq_pool,
                shutdown_event=lease_lost,
            ),
            name="controller.missed_event_drain",
        ),
        asyncio.create_task(
            intents_reconciler.run_loop(
                db_factory=db_factory,
                token_provider=lambda: current_token,
                shutdown_event=lease_lost,
            ),
            name="controller.intents_reconciler",
        ),
    ]
    renew_task = asyncio.create_task(
        _renew_loop(
            lease_backend=lease_backend,
            token_box=lambda: current_token,
            renew_interval_seconds=renew_interval_seconds,
            lease_lost=lease_lost,
            shutdown_event=shutdown_event,
        ),
        name="controller.renew",
    )
    children.append(renew_task)

    # Wait until either the lease is lost OR the supervisor is shutting down.
    waiter = asyncio.create_task(_wait_for_either(lease_lost, shutdown_event))
    try:
        await waiter
    finally:
        for child in children:
            child.cancel()
        for child in children:
            try:
                await child
            except (asyncio.CancelledError, Exception):
                continue

    # Best-effort release so a fast restart doesn't have to wait for TTL.
    try:
        await lease_backend.release(current_token)
        logger.info(
            "[CONTROLLER] released lease term=%d", current_token.term
        )
    except Exception:
        logger.warning("[CONTROLLER] release failed", exc_info=True)


async def _wait_for_either(a: asyncio.Event, b: asyncio.Event) -> None:
    """Wait for whichever Event fires first."""

    async def _wait(ev: asyncio.Event) -> None:
        await ev.wait()

    done, pending = await asyncio.wait(
        {asyncio.create_task(_wait(a)), asyncio.create_task(_wait(b))},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for p in pending:
        p.cancel()
        try:
            await p
        except (asyncio.CancelledError, Exception):
            pass


async def _renew_loop(
    *,
    lease_backend: Lease,
    token_box: Callable[[], LeaseToken],
    renew_interval_seconds: int,
    lease_lost: asyncio.Event,
    shutdown_event: asyncio.Event,
) -> None:
    """Renew the lease at a fixed interval; signal ``lease_lost`` on failure."""
    while not lease_lost.is_set() and not shutdown_event.is_set():
        try:
            await asyncio.wait_for(
                shutdown_event.wait(), timeout=renew_interval_seconds
            )
            # Shutdown — exit cleanly without renewing.
            return
        except TimeoutError:
            pass

        token = token_box()
        try:
            ok = await lease_backend.renew(token)
        except Exception:
            logger.exception(
                "[CONTROLLER] renew raised; treating as lease loss"
            )
            ok = False

        if not ok:
            logger.warning(
                "[CONTROLLER] lease lost (renew returned false) term=%d",
                token.term,
            )
            lease_lost.set()
            return

        logger.debug("[CONTROLLER] renewed lease term=%d", token.term)


def main() -> None:
    """Console-script entry point.

    Usage from the controller Deployment::

        command: ["python", "-m", "app.services.automations.controller_main"]
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run_controller())


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["run_controller", "main"]
