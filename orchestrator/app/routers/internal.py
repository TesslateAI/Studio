"""Internal API endpoints for cluster-internal services (CSI, GC, etc.).

Protected by Kubernetes NetworkPolicy — only CSI pods can reach these endpoints.
No authentication required.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Project

router = APIRouter(prefix="/internal", tags=["internal"])


@router.get("/known-volume-ids")
async def get_known_volume_ids(db: AsyncSession = Depends(get_db)):
    """Return all volume IDs referenced by projects.

    Used by the btrfs CSI garbage collector to identify orphaned volumes.
    Volumes not in this set (and past the grace period) are deleted.
    """
    result = await db.execute(select(Project.volume_id).where(Project.volume_id.isnot(None)))
    return {"volume_ids": [row[0] for row in result.all()]}
