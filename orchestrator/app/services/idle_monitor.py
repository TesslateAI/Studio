"""
Idle Monitor — background loops for compute idle shutdown and disk eviction.

Two independent loops:

1. **idle_monitor_loop** (every 60s): Finds active T2 environments past the idle
   threshold. Two phases:
   - Warning: publishes `idle_warning` WebSocket event.
   - Shutdown: transitions to 'stopping' and dispatches hibernate_project_bg().

2. **disk_eviction_loop** (every 300s): Evicts local btrfs volumes for projects
   that have been hibernated longer than the eviction threshold. Syncs to S3
   first, then deletes local data.

Both loops are registered under distributed locks so only one pod runs each.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

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
            # Also recover stuck "stopping" projects (>10 min)
            await _recover_stuck_stopping(db, now)
            return

        from .pubsub import get_pubsub

        pubsub = get_pubsub()

        for project in projects:
            try:
                if (
                    project.last_activity is not None
                    and project.last_activity > shutdown_cutoff
                ):
                    # Warning phase — still within grace period
                    remaining = (
                        project.last_activity
                        + idle_timeout
                        + grace
                        - now
                    )
                    minutes_left = max(0, int(remaining.total_seconds() / 60))

                    if pubsub:
                        await pubsub.publish_status_update(
                            project.owner_id,
                            project.id,
                            {
                                "type": "idle_warning",
                                "minutes_until_shutdown": minutes_left,
                                "message": (
                                    f"Environment will stop in {minutes_left} min"
                                    " due to inactivity"
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

                    asyncio.create_task(
                        hibernate_project_bg(project.id, project.owner_id)
                    )

            except Exception:
                logger.exception(
                    "[IDLE] Failed to process idle project %s", project.slug
                )

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


# =========================================================================
# Disk Eviction — separate loop for freeing local volumes
# =========================================================================

_EVICTION_INTERVAL_SECONDS = 300  # 5 min


async def disk_eviction_loop() -> None:
    """Evict local volumes for projects hibernated > threshold. Runs every 5 min."""
    logger.info("[EVICT] Disk eviction monitor started")

    while True:
        try:
            await _evict_dormant_volumes()
        except asyncio.CancelledError:
            logger.info("[EVICT] Disk eviction monitor cancelled")
            raise
        except Exception:
            logger.exception("[EVICT] Error in eviction loop")

        try:
            await asyncio.sleep(_EVICTION_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("[EVICT] Disk eviction monitor cancelled during sleep")
            raise


async def _evict_dormant_volumes() -> None:
    """Find hibernated projects with local volumes past the dormancy threshold. Evict to free disk."""
    settings = get_settings()
    eviction_threshold = timedelta(hours=settings.k8s_eviction_dormancy_hours)
    now = datetime.now(UTC)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Project)
            .options(selectinload(Project.containers))
            .where(Project.environment_status == "hibernated")
            .where(Project.volume_state == "local")
            .where(Project.hibernated_at < now - eviction_threshold)
        )
        projects = result.scalars().all()

        if not projects:
            return

        from .volume_manager import get_volume_manager

        vm = get_volume_manager()

        for project in projects:
            if not project.volume_id or not project.node_name:
                continue
            try:
                # Sync first, then evict
                await vm.trigger_sync(project.volume_id, project.node_name)

                service_dirs = [
                    c.directory
                    for c in (project.containers or [])
                    if getattr(c, "container_type", "base") == "service"
                    and c.directory
                ]
                await vm.evict_local_data(
                    project.volume_id, project.node_name, service_dirs
                )

                project.volume_state = "remote_only"
                project.node_name = None
                await db.commit()

                logger.info("[EVICT] Evicted volume for %s", project.slug)
            except Exception:
                logger.exception("[EVICT] Failed to evict %s", project.slug)
