from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from ..database import get_db
from ..users import current_active_user, current_superuser
from sqlalchemy.ext.asyncio import AsyncSession
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/track-landing")
async def track_landing(request: Request, ref: str):
    """Track when someone lands on the site via a referral link."""
    from ..referral_db import save_landing
    from ..services.discord_service import discord_service
    from ..services.ntfy_service import ntfy_service
    
    # Get client info
    ip_address = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")
    user_agent = request.headers.get("User-Agent", "")
    
    # Save to database
    save_landing(ref, ip_address, user_agent)
    
    # Send Discord notification (green for referral landing)
    try:
        await discord_service.send_referral_landing_notification(ref, ip_address)
    except Exception as e:
        logger.error(f"Failed to send Discord landing notification: {e}")
    
    # Send ntfy notification
    try:
        await ntfy_service.send_referral_landing(ref)
    except Exception as e:
        logger.error(f"Failed to send ntfy landing notification: {e}")
    
    return {"status": "tracked"}

@router.get("/referrals/stats")
async def get_referral_statistics():
    """Get referral statistics for all referrers."""
    from ..referral_db import get_all_referral_stats
    
    stats = get_all_referral_stats()
    return {"stats": stats}
