"""Orphan reaper for the Apps installer saga.

When the installer crashes between ``hub_client.create_volume_from_bundle``
and the final commit, the Hub-side volume is orphaned — no Project,
Container, or AppInstance row references it. The ledger row
(``AppInstallAttempt``) written immediately after the Hub call is the only
persistent evidence that the volume exists.

The reaper scans for ``AppInstallAttempt`` rows in state ``hub_created``
older than ``max_age_seconds`` (default 15 min grace window), and for each:

1. Acquires a row-level lock via ``SELECT ... FOR UPDATE SKIP LOCKED``
   (matches existing multi-pod patterns like
   ``schedule_triggers.process_trigger_events_batch``).
2. Checks convergence: if any ``AppInstance`` in ``state='installed'`` now
   points at the same ``volume_id``, the saga raced to committed — flip
   the row and skip.
3. Otherwise, call ``hub_client.delete_volume`` and mark the row
   ``state='reaped'`` with ``reaped_at``.
4. On Hub failure: mark ``state='reap_failed'`` with ``last_error``; a
   later invocation of the reaper will retry.

Scheduled via ARQ cron (see ``worker.py``). Safe to run concurrently from
multiple worker pods.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AppInstallAttempt, AppInstance

logger = logging.getLogger(__name__)

_DEFAULT_MAX_AGE_SECONDS = 15 * 60  # 15-minute grace window


async def _find_candidates(
    db: AsyncSession,
    *,
    max_age_seconds: int,
    limit: int,
) -> list[AppInstallAttempt]:
    cutoff = datetime.now(UTC) - timedelta(seconds=max_age_seconds)
    stmt = (
        select(AppInstallAttempt)
        .where(
            AppInstallAttempt.state == "hub_created",
            AppInstallAttempt.created_at < cutoff,
        )
        .order_by(AppInstallAttempt.created_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list((await db.execute(stmt)).scalars().all())


async def _converged_app_instance_for(
    db: AsyncSession, attempt: AppInstallAttempt
) -> AppInstance | None:
    """Return an installed AppInstance that references the same volume, if any.

    The installer's post-Hub commit path may race with the reaper. If a
    matching installed instance now exists, we must NOT reap — the saga
    succeeded and the ``committed_at`` flip call simply lost the race.
    """
    if attempt.volume_id is None:
        return None
    stmt = select(AppInstance).where(
        AppInstance.volume_id == attempt.volume_id,
        AppInstance.state == "installed",
    )
    return (await db.execute(stmt)).scalars().first()


async def reap_orphaned_install_attempts(
    hub_client: Any,
    *,
    max_age_seconds: int = _DEFAULT_MAX_AGE_SECONDS,
    limit: int = 50,
) -> dict[str, int]:
    """Scan for orphan install attempts and reap them.

    Parameters
    ----------
    hub_client:
        Anything exposing an async ``delete_volume(volume_id: str)`` method.
        Passing a live ``HubClient`` in production; tests can substitute a
        fake.
    max_age_seconds:
        Grace window before an attempt is eligible for reaping. Install
        latency p99 is well under a minute; 15 min is deliberately lax.
    limit:
        Max rows to inspect per invocation. Keeps the cron tick bounded.

    Returns
    -------
    dict with counters ``{"scanned", "converged", "reaped", "failed"}``.
    """
    from ...database import AsyncSessionLocal

    counters = {"scanned": 0, "converged": 0, "reaped": 0, "failed": 0}
    async with AsyncSessionLocal() as db:
        try:
            candidates = await _find_candidates(db, max_age_seconds=max_age_seconds, limit=limit)
        except Exception:
            logger.exception("install_reaper: failed to fetch candidates")
            await db.rollback()
            return counters

        for attempt in candidates:
            counters["scanned"] += 1
            converged = await _converged_app_instance_for(db, attempt)
            if converged is not None:
                attempt.state = "committed"
                attempt.app_instance_id = converged.id
                attempt.committed_at = datetime.now(UTC)
                counters["converged"] += 1
                continue

            if not attempt.volume_id:
                # No volume id means nothing to reap; just close the ledger.
                attempt.state = "reaped"
                attempt.reaped_at = datetime.now(UTC)
                continue

            try:
                await hub_client.delete_volume(attempt.volume_id)
            except Exception as exc:
                logger.exception(
                    "install_reaper: delete_volume failed attempt=%s volume=%s",
                    attempt.id,
                    attempt.volume_id,
                )
                attempt.state = "reap_failed"
                attempt.last_error = repr(exc)[:500]
                counters["failed"] += 1
                continue

            attempt.state = "reaped"
            attempt.reaped_at = datetime.now(UTC)
            counters["reaped"] += 1
            logger.info(
                "install_reaper: reaped volume=%s attempt=%s",
                attempt.volume_id,
                attempt.id,
            )

        try:
            await db.commit()
        except Exception:
            logger.exception("install_reaper: failed to commit reaper updates")
            await db.rollback()

    return counters
