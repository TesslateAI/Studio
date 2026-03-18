"""
Hibernate — shared background hibernation logic.

Used by both the user-facing hibernate endpoint and the idle monitor.
Stops compute, syncs volume back to Hub, and transitions to 'hibernated'.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

logger = logging.getLogger(__name__)


async def hibernate_project_bg(project_id: UUID, user_id: UUID) -> None:
    """Background: stop compute, sync to Hub, mark hibernated.

    Safe to call from asyncio.create_task() — opens its own DB session,
    catches all exceptions, and always leaves the project in a valid state.
    """
    from ..database import AsyncSessionLocal
    from ..models import Project

    async with AsyncSessionLocal() as db:
        project = await db.get(Project, project_id)
        if not project or project.environment_status != "stopping":
            return

        try:
            # Notify frontend immediately
            from .pubsub import get_pubsub

            pubsub = get_pubsub()
            if pubsub:
                await pubsub.publish_status_update(
                    user_id,
                    project_id,
                    {
                        "type": "environment_stopping",
                        "message": "Stopping environment...",
                    },
                )

            if project.compute_tier == "environment":
                from .compute_manager import get_compute_manager

                cm = get_compute_manager()
                await cm.stop_environment(project, db)

            # Trigger S3 sync on the node that owns the volume
            if project.volume_id:
                try:
                    from .volume_manager import get_volume_manager

                    vm = get_volume_manager()
                    await vm.trigger_sync(project.volume_id)
                except Exception:
                    logger.warning(
                        "[HIBERNATE] Sync trigger failed for project %s — Hub "
                        "will catch up on next access",
                        project_id,
                    )

            project.environment_status = "hibernated"
            project.hibernated_at = datetime.now(UTC)
            await db.commit()

            if pubsub:
                await pubsub.publish_status_update(
                    user_id,
                    project_id,
                    {
                        "type": "environment_stopped",
                        "reason": "user",
                        "message": "Environment stopped",
                    },
                )

            logger.info("[HIBERNATE] Project %s hibernated successfully", project_id)

        except Exception:
            logger.exception("[HIBERNATE] Failed for project %s", project_id)
            project.environment_status = "stopped"
            await db.commit()
