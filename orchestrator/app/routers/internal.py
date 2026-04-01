"""Internal API endpoints for cluster-internal services (CSI, GC, etc.).

Protected by Kubernetes NetworkPolicy — only CSI pods can reach these endpoints.
No authentication required.
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Project

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal", tags=["internal"])


@router.get("/known-volume-ids")
async def get_known_volume_ids(db: AsyncSession = Depends(get_db)):
    """Return all volume IDs referenced by projects.

    Used by the btrfs CSI garbage collector to identify orphaned volumes.
    Volumes not in this set (and past the grace period) are deleted.
    """
    result = await db.execute(select(Project.volume_id).where(Project.volume_id.isnot(None)))
    return {"volume_ids": [row[0] for row in result.all()]}


@router.post("/volume-events")
async def volume_event(payload: dict, db: AsyncSession = Depends(get_db)):
    """Receive volume lifecycle events from the Hub.

    The Hub POSTs here after completing async operations (EnsureCached,
    DeleteVolumeFromNode) so the frontend can be notified in real time
    via WebSocket. Events: "ready", "deleted".
    """
    volume_id = payload.get("volume_id")
    event = payload.get("event")
    if not volume_id or not event:
        return {"status": "ignored"}

    result = await db.execute(
        select(Project.id, Project.owner_id).where(Project.volume_id == volume_id)
    )
    row = result.first()
    if not row:
        return {"status": "no_project"}

    project_id, owner_id = row

    try:
        from ..services.pubsub import get_pubsub

        pubsub = get_pubsub()
        if pubsub:
            await pubsub.publish_status_update(
                owner_id,
                project_id,
                {"type": f"volume_{event}", "volume_id": volume_id},
            )
    except Exception:
        logger.warning("Failed to publish volume event %s for %s", event, volume_id)

    return {"status": "ok"}
