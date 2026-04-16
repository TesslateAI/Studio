import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User
from ..users import current_active_user

logger = logging.getLogger(__name__)

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post("/track-landing")
@limiter.limit("10/minute")
async def track_landing(request: Request, ref: str, db: AsyncSession = Depends(get_db)):
    """Track when someone lands on the site via a referral link."""
    from ..referral_db import save_landing
    from ..services.discord_service import discord_service
    from ..services.ntfy_service import ntfy_service

    # Validate that the ref code belongs to an existing user
    result = await db.execute(select(User).where(User.referral_code == ref))
    if result.scalars().first() is None:
        raise HTTPException(status_code=404, detail="Unknown referral code")

    # Get client info
    ip_address = request.headers.get(
        "X-Forwarded-For", request.client.host if request.client else "unknown"
    )
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
async def get_referral_statistics(current_user: User = Depends(current_active_user)):
    """Get referral statistics scoped to the authenticated user's referral code."""
    from ..referral_db import get_referral_stats

    if not current_user.referral_code:
        return {"stats": []}

    stats = get_referral_stats(current_user.referral_code)
    return {"stats": [stats]}
