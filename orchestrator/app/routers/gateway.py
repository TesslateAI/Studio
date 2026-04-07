"""
Gateway API — status, reload, platform info, identity pairing.

These endpoints let the frontend and admin tools interact with the gateway
process and manage platform identity linking.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import PlatformIdentity, User
from ..users import current_active_user, current_superuser

router = APIRouter(prefix="/api/gateway", tags=["gateway"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PairVerifyRequest(BaseModel):
    platform: str
    pairing_code: str


class PlatformIdentityResponse(BaseModel):
    id: UUID
    platform: str
    platform_user_id: str
    platform_username: str | None
    is_verified: bool
    paired_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class GatewayStatusResponse(BaseModel):
    shard: int | None = None
    adapters: int | None = None
    active_sessions: int | None = None
    heartbeat: str | None = None
    status: str = "unknown"


class PlatformInfo(BaseModel):
    platform: str
    display_name: str
    supports_gateway: bool
    setup_notes: str


# ---------------------------------------------------------------------------
# Gateway status (reads from Redis, no direct comms with gateway process)
# ---------------------------------------------------------------------------


@router.get("/status", response_model=GatewayStatusResponse)
async def gateway_status():
    """Read gateway status from Redis."""
    try:
        from ..services.cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return GatewayStatusResponse(status="redis_unavailable")

        import json

        raw = await redis.get("tesslate:gateway:status")
        if not raw:
            return GatewayStatusResponse(status="offline")

        data = json.loads(raw)
        return GatewayStatusResponse(
            shard=data.get("shard"),
            adapters=data.get("adapters"),
            active_sessions=data.get("active_sessions"),
            heartbeat=data.get("heartbeat"),
            status="online",
        )
    except Exception as e:
        logger.warning("[GATEWAY-API] Status read failed: %s", e)
        return GatewayStatusResponse(status="error")


@router.post("/reload")
async def gateway_reload(user: User = Depends(current_superuser)):
    """Signal the gateway process to reload configurations."""
    try:
        from ..services.cache_service import get_redis_client

        redis = await get_redis_client()
        if redis:
            await redis.publish("tesslate:gateway:reload", "reload")
            return {"status": "reload_signalled"}
        return {"status": "redis_unavailable"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/platforms", response_model=list[PlatformInfo])
async def list_platforms():
    """List supported messaging platforms and setup requirements."""
    return [
        PlatformInfo(
            platform="telegram",
            display_name="Telegram",
            supports_gateway=True,
            setup_notes="Create a bot via @BotFather and provide the bot token.",
        ),
        PlatformInfo(
            platform="discord",
            display_name="Discord",
            supports_gateway=True,
            setup_notes="Create a Discord app, enable Message Content intent, and provide the bot token.",
        ),
        PlatformInfo(
            platform="slack",
            display_name="Slack",
            supports_gateway=True,
            setup_notes="Create a Slack app with Socket Mode enabled. Provide bot token and app-level token.",
        ),
        PlatformInfo(
            platform="whatsapp",
            display_name="WhatsApp",
            supports_gateway=False,
            setup_notes="Configure via Meta Cloud API. Webhook-only, no persistent gateway connection.",
        ),
        PlatformInfo(
            platform="signal",
            display_name="Signal",
            supports_gateway=True,
            setup_notes="Requires a self-hosted signal-cli REST API instance.",
        ),
        PlatformInfo(
            platform="cli",
            display_name="CLI",
            supports_gateway=True,
            setup_notes="Built-in WebSocket adapter for CLI clients.",
        ),
    ]


# ---------------------------------------------------------------------------
# Identity pairing
# ---------------------------------------------------------------------------


@router.post("/pair/verify")
async def verify_pairing_code(
    payload: PairVerifyRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify a pairing code and link a platform identity to the current user."""
    now = datetime.now(UTC)

    logger.info(
        "[GATEWAY] Pair verify attempt: platform=%s, code=%s",
        payload.platform,
        payload.pairing_code,
    )

    result = await db.execute(
        select(PlatformIdentity).where(
            PlatformIdentity.platform == payload.platform,
            PlatformIdentity.pairing_code == payload.pairing_code,
            PlatformIdentity.is_verified.is_(False),
        )
    )
    identity = result.scalar_one_or_none()

    if not identity:
        # Debug: check if code exists at all
        debug = await db.execute(
            select(PlatformIdentity).where(PlatformIdentity.pairing_code == payload.pairing_code)
        )
        debug_row = debug.scalar_one_or_none()
        if debug_row:
            logger.warning(
                "[GATEWAY] Code found but filtered out: verified=%s, platform=%s (requested=%s)",
                debug_row.is_verified,
                debug_row.platform,
                payload.platform,
            )
        else:
            logger.warning("[GATEWAY] Code %s not found in DB at all", payload.pairing_code)
        raise HTTPException(status_code=404, detail="Invalid or expired pairing code")

    if identity.pairing_expires_at and identity.pairing_expires_at < now:
        raise HTTPException(status_code=410, detail="Pairing code expired")

    # Link to current user
    identity.user_id = user.id
    identity.is_verified = True
    identity.pairing_code = None
    identity.pairing_expires_at = None
    identity.paired_at = now
    await db.commit()

    logger.info(
        "[GATEWAY] Paired %s identity %s to user %s",
        payload.platform,
        identity.platform_user_id,
        user.id,
    )

    return {"status": "paired", "platform": payload.platform}


@router.get("/identities", response_model=list[PlatformIdentityResponse])
async def list_identities(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's linked platform identities."""
    result = await db.execute(
        select(PlatformIdentity)
        .where(
            PlatformIdentity.user_id == user.id,
            PlatformIdentity.is_verified.is_(True),
        )
        .order_by(PlatformIdentity.created_at.desc())
    )
    return result.scalars().all()


@router.delete("/identities/{identity_id}")
async def unlink_identity(
    identity_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Unlink a platform identity."""
    result = await db.execute(
        select(PlatformIdentity).where(
            PlatformIdentity.id == identity_id,
            PlatformIdentity.user_id == user.id,
        )
    )
    identity = result.scalar_one_or_none()
    if not identity:
        raise HTTPException(status_code=404, detail="Identity not found")

    await db.delete(identity)
    await db.commit()

    return {"status": "unlinked", "platform": identity.platform}
