"""
Idle Monitor — background loop for compute idle shutdown.

Finds active T2 environments past the idle threshold:
- Warning: publishes `idle_warning` WebSocket event.
- Shutdown: transitions to 'stopping' and dispatches hibernate_project_bg().

Disk eviction is no longer handled here — the Volume Hub manages cache
lifecycle autonomously.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select

from ..config import get_settings
from ..database import AsyncSessionLocal
from ..models import Project

logger = logging.getLogger(__name__)

# Grace period after idle timeout before shutdown (minutes)
_WARNING_GRACE_MINUTES = 5


async def idle_monitor_loop() -> None:
    """Check every 60s for idle T2 environments and scale them to zero."""
    logger.info("[IDLE] Idle environment monitor started")

    while True:
        try:
            await _check_idle_environments()
        except asyncio.CancelledError:
            logger.info("[IDLE] Idle monitor cancelled")
            raise
        except Exception:
            logger.exception("[IDLE] Error in idle monitor loop")

        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            logger.info("[IDLE] Idle monitor cancelled during sleep")
            raise


async def _check_idle_environments() -> None:
    settings = get_settings()
    idle_timeout = timedelta(minutes=settings.k8s_hibernation_idle_minutes)
    grace = timedelta(minutes=_WARNING_GRACE_MINUTES)

    now = datetime.now(UTC)
    warning_cutoff = now - idle_timeout
    shutdown_cutoff = now - (idle_timeout + grace)

    async with AsyncSessionLocal() as db:
        # Find active environments past idle threshold
        result = await db.execute(
            select(Project)
            .where(Project.compute_tier == "environment")
            .where(Project.environment_status == "active")
            .where(
                or_(
                    Project.last_activity < warning_cutoff,
                    Project.last_activity.is_(None),
                )
            )
        )
        projects = result.scalars().all()

        if not projects:
            # Also recover stuck "stopping" projects
            await _recover_stuck_stopping(db, now)
            return

        from .pubsub import get_pubsub

        pubsub = get_pubsub()

        for project in projects:
            try:
                if project.last_activity is not None and project.last_activity > shutdown_cutoff:
                    # Warning phase — still within grace period
                    remaining = project.last_activity + idle_timeout + grace - now
                    minutes_left = max(0, int(remaining.total_seconds() / 60))

                    if pubsub:
                        await pubsub.publish_status_update(
                            project.owner_id,
                            project.id,
                            {
                                "type": "idle_warning",
                                "minutes_until_shutdown": minutes_left,
                                "message": (
                                    f"Environment will stop in {minutes_left} min due to inactivity"
                                ),
                            },
                        )
                    logger.info(
                        "[IDLE] Warning sent for project %s (%d min left)",
                        project.slug,
                        minutes_left,
                    )
                else:
                    # Past grace — transition to stopping and dispatch background task
                    logger.info(
                        "[IDLE] Stopping idle environment for project %s",
                        project.slug,
                    )

                    project.environment_status = "stopping"
                    await db.commit()

                    from .hibernate import hibernate_project_bg

                    asyncio.create_task(hibernate_project_bg(project.id, project.owner_id))

            except Exception:
                logger.exception("[IDLE] Failed to process idle project %s", project.slug)

        # Recover stuck "stopping" projects
        await _recover_stuck_stopping(db, now)


async def _recover_stuck_stopping(db, now: datetime) -> None:
    """Reset projects stuck in 'stopping' for >10 min back to 'stopped'."""
    stuck = await db.execute(
        select(Project).where(
            Project.environment_status == "stopping",
            or_(
                Project.last_activity < now - timedelta(minutes=10),
                Project.last_activity.is_(None),
            ),
        )
    )
    stuck_projects = stuck.scalars().all()
    for p in stuck_projects:
        logger.warning(
            "[IDLE] Recovering stuck project %s from 'stopping' to 'stopped'",
            p.slug,
        )
        p.environment_status = "stopped"
    if stuck_projects:
        await db.commit()
