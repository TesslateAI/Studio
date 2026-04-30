"""
Auto-add canonical agents to every user's library.

Lives under ``services/`` (not ``seeds/``) because, after Wave 10, the
orchestrator no longer ships the catalog rows themselves — the federation
sync worker pulls them from the marketplace service. This module is
strictly user-state seeding: it sweeps every user and inserts a
``UserPurchasedAgent`` row for each canonical agent the user is missing,
so canonical agents (Tesslate Agent, Librarian, Agent Builder,
Automation Builder, Service Integrator) appear in every user's library
and ``@``-mention picker without manual install.

Each function is idempotent: re-running on a healthy DB is a no-op except
for an explicit "pin to top of library" refresh on the Tesslate Agent
row's ``purchase_date``. A function whose target slug has not yet been
synced into the local catalog cache logs a warning and returns 0 — boot
must never block on a temporarily-empty catalog (the next sync poll will
populate the row, and the next call to this function will pick it up).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MarketplaceAgent, UserPurchasedAgent
from ..models_auth import User

logger = logging.getLogger(__name__)


async def _add_agent_to_users_by_slug(
    db: AsyncSession,
    *,
    slug: str,
    display_name: str,
) -> int:
    """Generic: add a canonical agent to every user's library.

    Returns the number of (UserPurchasedAgent rows inserted +
    backfilled-team_id) so the caller can log a single boot summary.
    """
    result = await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.slug == slug))
    agent = result.scalar_one_or_none()
    if not agent:
        logger.warning(
            "%s (slug=%s) not found in local catalog cache; sync worker will "
            "populate it on its next poll. Skipping auto-add this boot.",
            display_name,
            slug,
        )
        return 0

    result = await db.execute(select(User))
    users = result.scalars().all()
    added = 0

    for user in users:
        result = await db.execute(
            select(UserPurchasedAgent).where(
                UserPurchasedAgent.user_id == user.id,
                UserPurchasedAgent.agent_id == agent.id,
            )
        )
        existing = result.scalars().first()

        if existing:
            # Backfill team_id on records created before the team feature shipped.
            if existing.team_id is None and user.default_team_id is not None:
                existing.team_id = user.default_team_id
                added += 1
            continue

        purchase = UserPurchasedAgent(
            user_id=user.id,
            team_id=user.default_team_id,
            agent_id=agent.id,
            purchase_type="free",
            is_active=True,
        )
        db.add(purchase)
        added += 1

    if added:
        await db.commit()
        logger.info("Auto-added %s for %d users", display_name, added)
    else:
        logger.debug("All users already have %s", display_name)

    return added


async def auto_add_librarian_agent_to_users(db: AsyncSession) -> int:
    """Add the Librarian agent to all users who don't have it yet."""
    return await _add_agent_to_users_by_slug(db, slug="librarian", display_name="Librarian")


async def auto_add_agent_builder_to_users(db: AsyncSession) -> int:
    """Add the Agent Builder to all users who don't have it yet."""
    return await _add_agent_to_users_by_slug(db, slug="agent-builder", display_name="Agent Builder")


async def auto_add_automation_builder_to_users(db: AsyncSession) -> int:
    """Add the Automation Builder to all users who don't have it yet."""
    return await _add_agent_to_users_by_slug(
        db, slug="automation-builder", display_name="Automation Builder"
    )


async def auto_add_service_integrator_to_users(db: AsyncSession) -> int:
    """Add the Service Integrator agent to all users who don't have it yet."""
    return await _add_agent_to_users_by_slug(
        db, slug="service-integrator", display_name="Service Integrator"
    )


async def auto_add_tesslate_agent_to_users(db: AsyncSession) -> int:
    """Add the Tesslate Agent to all users and pin it to the top of every
    library.

    Library order is ``purchase_date DESC``; the chat picks ``library[0]`` as
    the default agent. Refreshing ``purchase_date`` to NOW() on every boot
    keeps Tesslate Agent at the top regardless of when the other auto-add
    functions seeded their rows.

    Also clears ``selected_model`` so users always fall back to the agent's
    canonical model (currently kimi-k2.5).
    """
    result = await db.execute(
        select(MarketplaceAgent).where(MarketplaceAgent.slug == "tesslate-agent")
    )
    tesslate_agent = result.scalar_one_or_none()
    if not tesslate_agent:
        logger.warning(
            "Tesslate Agent (slug=tesslate-agent) not found in local catalog "
            "cache; sync worker will populate it on its next poll. Skipping "
            "auto-add + top-pin this boot."
        )
        return 0

    result = await db.execute(select(User))
    users = result.scalars().all()
    added = 0

    for user in users:
        result = await db.execute(
            select(UserPurchasedAgent).where(
                UserPurchasedAgent.user_id == user.id,
                UserPurchasedAgent.agent_id == tesslate_agent.id,
            )
        )
        existing = result.scalars().first()

        if existing:
            if existing.team_id is None and user.default_team_id is not None:
                existing.team_id = user.default_team_id
            continue

        purchase = UserPurchasedAgent(
            user_id=user.id,
            team_id=user.default_team_id,
            agent_id=tesslate_agent.id,
            purchase_type="free",
            is_active=True,
        )
        db.add(purchase)
        added += 1

    # Pin to the top of every library on every restart, and clear per-user
    # model overrides so the canonical model takes effect.
    await db.execute(
        update(UserPurchasedAgent)
        .where(UserPurchasedAgent.agent_id == tesslate_agent.id)
        .values(purchase_date=datetime.now(timezone.utc), selected_model=None)
    )

    await db.commit()
    if added:
        logger.info("Added Tesslate Agent for %d users; refreshed top-pin for all", added)
    else:
        logger.debug("All users already have Tesslate Agent; refreshed top-pin for all")

    return added


__all__ = [
    "auto_add_agent_builder_to_users",
    "auto_add_automation_builder_to_users",
    "auto_add_librarian_agent_to_users",
    "auto_add_service_integrator_to_users",
    "auto_add_tesslate_agent_to_users",
]
