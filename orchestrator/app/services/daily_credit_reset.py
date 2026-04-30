"""
Background task for resetting daily credits for free-tier teams
and expiring signup bonuses.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from ..config import get_settings
from ..database import AsyncSessionLocal
from ..models_team import Team

logger = logging.getLogger(__name__)
settings = get_settings()


async def daily_credit_reset_loop():
    """
    Background loop that runs every hour to:
    1. Reset daily credits for free-tier teams whose reset date has passed
    2. Zero out expired signup bonuses on teams
    3. Reset bundled credits for paid-tier teams

    All resets are based on UTC midnight. Users in different timezones will see
    their daily credits refresh at different local times (e.g., 7 PM EST, 4 PM PST).
    """
    logger.info("Daily credit reset loop started")

    while True:
        try:
            await _reset_team_daily_credits()
            await _expire_team_signup_bonuses()
            await _reset_team_bundled_credits()
        except Exception as e:
            logger.error(f"Error in daily credit reset loop: {e}", exc_info=True)

        # Run every hour
        await asyncio.sleep(3600)


# ── Team-level resets ───────────────────────────────────────────────────


async def _reset_team_daily_credits():
    """Reset daily credits for free-tier teams whose reset date has passed."""
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Team).where(
                Team.subscription_tier == "free",
                (Team.daily_credits_reset_date < today_start)
                | (Team.daily_credits_reset_date.is_(None)),
            )
        )
        teams = result.scalars().all()

        if not teams:
            return

        for team in teams:
            team.daily_credits = settings.tier_daily_credits_free
            team.daily_credits_reset_date = now

        await session.commit()
        logger.info(f"Reset daily credits for {len(teams)} free-tier teams")


async def _expire_team_signup_bonuses():
    """Zero out signup bonus credits on teams that have expired."""
    now = datetime.now(UTC)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(Team)
            .where(
                Team.signup_bonus_credits > 0,
                Team.signup_bonus_expires_at.isnot(None),
                Team.signup_bonus_expires_at < now,
            )
            .values(signup_bonus_credits=0)
        )

        if result.rowcount > 0:
            await session.commit()
            logger.info(f"Expired signup bonuses for {result.rowcount} teams")


async def _reset_team_bundled_credits():
    """Reset bundled credits for paid-tier teams whose credits_reset_date has passed."""
    now = datetime.now(UTC)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Team).where(
                Team.subscription_tier != "free",
                Team.credits_reset_date.isnot(None),
                Team.credits_reset_date <= now,
            )
        )
        teams = result.scalars().all()

        if not teams:
            return

        for team in teams:
            tier_credits = settings.get_tier_bundled_credits(team.subscription_tier)
            team.bundled_credits = tier_credits
            team.credits_reset_date = now + timedelta(days=30)

        await session.commit()
        logger.info(f"Reset bundled credits for {len(teams)} paid-tier teams")
