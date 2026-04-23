"""Internal API endpoints for cluster-internal services (CSI, GC, etc.).

Protected by two layers:
  1. X-Internal-Secret header (shared secret, verified by verify_internal_secret below)
  2. Kubernetes NetworkPolicy — only Hub/CSI pods can reach these endpoints
  3. NGINX Ingress server-snippet — /api/internal/* is blocked at the edge

Desktop mode skips secret enforcement (Hub does not run on desktop).
"""

import hmac
import logging
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models import Project

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal", tags=["internal"])

_startup_time = time.monotonic()


async def verify_internal_secret(request: Request) -> None:
    """Verify X-Internal-Secret header for cluster-internal callers.

    During the grace period after process start, missing/wrong secrets are
    logged but allowed through to avoid a hard failure window during rolling
    deploys.  After the grace period, any mismatch returns 403.

    Desktop mode skips enforcement entirely — the Hub does not run on desktop.
    """
    settings = get_settings()

    if settings.is_desktop_mode:
        return

    provided = request.headers.get("X-Internal-Secret", "")
    expected = settings.internal_api_secret

    if expected and hmac.compare_digest(provided.encode(), expected.encode()):
        return

    elapsed = time.monotonic() - _startup_time
    grace = settings.internal_secret_grace_seconds
    if elapsed < grace:
        logger.warning(
            "X-Internal-Secret missing or wrong — allowing during grace period (%.0fs remaining)",
            grace - elapsed,
        )
        return

    raise HTTPException(status_code=403, detail="Forbidden")


class VolumeEventPayload(BaseModel):
    volume_id: str
    event: Literal["ready", "deleted"]


@router.get("/known-volume-ids", dependencies=[Depends(verify_internal_secret)])
async def get_known_volume_ids(db: AsyncSession = Depends(get_db)):
    """Return all volume IDs referenced by projects.

    Used by the btrfs CSI garbage collector to identify orphaned volumes.
    Volumes not in this set (and past the grace period) are deleted.
    """
    result = await db.execute(select(Project.volume_id).where(Project.volume_id.isnot(None)))
    return {"volume_ids": [row[0] for row in result.all()]}


@router.post("/volume-events", dependencies=[Depends(verify_internal_secret)])
async def volume_event(payload: VolumeEventPayload, db: AsyncSession = Depends(get_db)):
    """Receive volume lifecycle events from the Hub.

    The Hub POSTs here after completing async operations (EnsureCached,
    DeleteVolumeFromNode) so the frontend can be notified in real time
    via WebSocket. Events: "ready", "deleted".
    """
    volume_id = payload.volume_id
    event = payload.event

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
