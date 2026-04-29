"""
Seed open-source marketplace agents.

Currently empty — community agents are not seeded by default. The seed
function still runs as a no-op so callers can rely on a stable interface.

Can be run standalone or called from the startup seeder.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MarketplaceAgent
from ..services.marketplace_constants import TESSLATE_OFFICIAL_ID
from .marketplace_agents import get_or_create_tesslate_account

logger = logging.getLogger(__name__)

OPENSOURCE_AGENTS: list[dict] = []


async def seed_opensource_agents(db: AsyncSession) -> int:
    """Seed open-source marketplace agents. Upserts by slug.

    Returns:
        Number of newly created agents.
    """
    from ..config import get_settings
    default_model = get_settings().default_model

    tesslate_user = await get_or_create_tesslate_account(db)
    created = 0
    updated = 0

    for agent_data in OPENSOURCE_AGENTS:
        agent_data = {**agent_data, "model": default_model}
        result = await db.execute(
            select(MarketplaceAgent).where(MarketplaceAgent.slug == agent_data["slug"])
        )
        existing = result.scalar_one_or_none()

        if existing:
            for key, value in agent_data.items():
                if key != "slug":
                    setattr(existing, key, value)
            if not existing.created_by_user_id:
                existing.created_by_user_id = tesslate_user.id
            if not existing.source_id:
                existing.source_id = TESSLATE_OFFICIAL_ID
            updated += 1
            logger.info("Updated open-source agent: %s", agent_data["slug"])
        else:
            agent = MarketplaceAgent(
                **agent_data,
                created_by_user_id=tesslate_user.id,
                source_id=TESSLATE_OFFICIAL_ID,
            )
            db.add(agent)
            created += 1
            logger.info("Created open-source agent: %s", agent_data["name"])

    await db.commit()

    logger.info(
        "Open-source agents: %d created, %d updated",
        created,
        updated,
    )
    return created
