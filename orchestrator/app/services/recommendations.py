"""
Recommendation service for marketplace.

Implements O(n) co-installation tracking algorithm:
- When user installs agent X, we look at their existing installed agents [A, B, C]
- For each pair (A, X), (B, X), (C, X), we increment the co-install count
- This runs as a background task (non-blocking)

For "People also like" queries:
- Look up agents that are frequently co-installed with the current agent
- Return top N sorted by co_install_count
- O(1) lookup since we query by agent_id
"""
import logging
from uuid import UUID
from typing import List, Optional

from sqlalchemy import select, update, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from ..models import AgentCoInstall, MarketplaceAgent, UserPurchasedAgent

logger = logging.getLogger(__name__)


async def update_co_install_counts(
    db: AsyncSession,
    user_id: UUID,
    new_agent_id: UUID
) -> None:
    """
    Update co-installation counts when a user installs a new agent.

    This is called as a background task (non-blocking).
    Algorithm: O(n) where n = number of agents user has installed.

    Args:
        db: Database session
        user_id: ID of the user who installed the agent
        new_agent_id: ID of the newly installed agent
    """
    try:
        # Get all agents the user has installed (excluding the new one)
        result = await db.execute(
            select(UserPurchasedAgent.agent_id).where(
                UserPurchasedAgent.user_id == user_id,
                UserPurchasedAgent.agent_id != new_agent_id,
                UserPurchasedAgent.is_active == True
            )
        )
        existing_agent_ids = [row[0] for row in result.fetchall()]

        if not existing_agent_ids:
            logger.debug(f"No existing agents for user {user_id}, skipping co-install update")
            return

        # For each existing agent, update the co-install count
        # We need to update both directions: (existing, new) and (new, existing)
        for existing_id in existing_agent_ids:
            # Upsert for (existing, new)
            await _upsert_co_install(db, existing_id, new_agent_id)
            # Upsert for (new, existing)
            await _upsert_co_install(db, new_agent_id, existing_id)

        await db.commit()
        logger.info(f"Updated co-install counts for agent {new_agent_id} with {len(existing_agent_ids)} related agents")

    except Exception as e:
        logger.error(f"Failed to update co-install counts: {e}")
        await db.rollback()


async def _upsert_co_install(
    db: AsyncSession,
    agent_id: UUID,
    related_agent_id: UUID
) -> None:
    """
    Insert or update a co-install record.
    Uses PostgreSQL upsert (INSERT ... ON CONFLICT) for efficiency.
    """
    stmt = insert(AgentCoInstall).values(
        agent_id=agent_id,
        related_agent_id=related_agent_id,
        co_install_count=1
    ).on_conflict_do_update(
        constraint='uq_agent_co_install_pair',
        set_={'co_install_count': AgentCoInstall.co_install_count + 1}
    )
    await db.execute(stmt)


async def get_related_agents(
    db: AsyncSession,
    agent_slug: str,
    limit: int = 6,
    exclude_agent_ids: Optional[List[UUID]] = None
) -> List[dict]:
    """
    Get recommended agents based on co-installation patterns.

    Args:
        db: Database session
        agent_slug: Slug of the agent to find related agents for
        limit: Maximum number of related agents to return
        exclude_agent_ids: Agent IDs to exclude (e.g., already installed)

    Returns:
        List of related agent dictionaries
    """
    # First, get the agent ID from slug
    agent_result = await db.execute(
        select(MarketplaceAgent).where(MarketplaceAgent.slug == agent_slug)
    )
    agent = agent_result.scalar_one_or_none()

    if not agent:
        return []

    exclude_ids = set(exclude_agent_ids or [])
    exclude_ids.add(agent.id)  # Don't include the agent itself

    # Get related agents sorted by co-install count
    query = select(
        AgentCoInstall.related_agent_id,
        AgentCoInstall.co_install_count
    ).where(
        AgentCoInstall.agent_id == agent.id
    ).order_by(
        AgentCoInstall.co_install_count.desc()
    ).limit(limit * 2)  # Get more than needed to account for filtering

    result = await db.execute(query)
    co_installs = result.fetchall()

    # If we have co-install data, use it
    related_ids = []
    for row in co_installs:
        if row[0] not in exclude_ids:
            related_ids.append(row[0])
            if len(related_ids) >= limit:
                break

    # If we don't have enough co-install data, fall back to same category
    if len(related_ids) < limit:
        fallback_result = await db.execute(
            select(MarketplaceAgent.id).where(
                MarketplaceAgent.category == agent.category,
                MarketplaceAgent.is_published == True,
                MarketplaceAgent.is_active == True,
                ~MarketplaceAgent.id.in_(exclude_ids | set(related_ids))
            ).order_by(MarketplaceAgent.downloads.desc()).limit(limit - len(related_ids))
        )
        for row in fallback_result.fetchall():
            related_ids.append(row[0])

    if not related_ids:
        return []

    # Fetch full agent details for the related agents
    agents_result = await db.execute(
        select(MarketplaceAgent).where(
            MarketplaceAgent.id.in_(related_ids),
            MarketplaceAgent.is_published == True,
            MarketplaceAgent.is_active == True
        )
    )
    agents = agents_result.scalars().all()

    # Build response maintaining the order from co_install_count
    id_to_agent = {a.id: a for a in agents}
    result_list = []
    for agent_id in related_ids:
        if agent_id in id_to_agent:
            a = id_to_agent[agent_id]
            result_list.append({
                "id": str(a.id),
                "name": a.name,
                "slug": a.slug,
                "description": a.description,
                "category": a.category,
                "item_type": a.item_type or "agent",
                "source_type": a.source_type or "closed",
                "is_forkable": a.is_forkable,
                "is_active": a.is_active,
                "icon": a.icon,
                "avatar_url": a.avatar_url,
                "pricing_type": a.pricing_type,
                "price": a.price,
                "downloads": a.downloads or 0,
                "rating": a.rating or 5.0,
                "reviews_count": a.reviews_count or 0,
                "usage_count": a.usage_count or 0,
                "features": a.features or [],
                "tags": a.tags or [],
                "is_featured": a.is_featured
            })

    return result_list
