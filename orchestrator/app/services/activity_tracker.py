"""
Activity Tracker Service

Database-based activity tracking for project idle cleanup.
Tracks: agent messages, file operations, terminal activity.

This replaces in-memory tracking to support horizontal scaling of the backend.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Project

logger = logging.getLogger(__name__)


async def track_project_activity(
    db: AsyncSession, project_id: UUID, activity_type: str = "general"
) -> None:
    """
    Update project's last_activity timestamp.

    Args:
        db: Database session
        project_id: Project UUID
        activity_type: Type of activity (agent, file, terminal, general)

    This should be called from:
    - Agent chat streaming (on each message)
    - File operations (save, create, delete)
    - Terminal activity (commands)
    """
    try:
        await db.execute(
            update(Project)
            .where(Project.id == project_id)
            .values(
                last_activity=datetime.now(UTC),
                environment_status="active",  # Ensure status is active
            )
        )
        await db.commit()
        logger.debug(f"[ACTIVITY] Tracked {activity_type} activity for project {project_id}")
    except Exception as e:
        logger.error(f"[ACTIVITY] Failed to track activity for {project_id}: {e}")
        # Don't raise - activity tracking failure shouldn't break the request


async def mark_project_environment_active(db: AsyncSession, project_id: UUID) -> None:
    """
    Mark project environment as active (K8s resources running).
    Called when project environment is started/opened.
    """
    try:
        await db.execute(
            update(Project)
            .where(Project.id == project_id)
            .values(
                environment_status="active", last_activity=datetime.now(UTC), hibernated_at=None
            )
        )
        await db.commit()
        logger.info(f"[ACTIVITY] Project {project_id} environment marked active")
    except Exception as e:
        logger.error(f"[ACTIVITY] Failed to mark project active: {e}")


async def mark_project_environment_hibernated(db: AsyncSession, project_id: UUID) -> None:
    """
    Mark project environment as hibernated (K8s resources deleted, files in S3).
    Called after successful hibernation.
    """
    try:
        await db.execute(
            update(Project)
            .where(Project.id == project_id)
            .values(environment_status="hibernated", hibernated_at=datetime.now(UTC))
        )
        await db.commit()
        logger.info(f"[ACTIVITY] Project {project_id} environment marked hibernated")
    except Exception as e:
        logger.error(f"[ACTIVITY] Failed to mark project hibernated: {e}")
