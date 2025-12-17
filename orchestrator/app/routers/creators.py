"""
Creator/Author profile API endpoints for the marketplace.
"""
from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_

from ..database import get_db
from ..models import MarketplaceAgent
from ..models_auth import User

router = APIRouter(prefix="/api/creators", tags=["creators"])


@router.get("/{user_id}")
async def get_creator_profile(
    user_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get a creator's public profile and their published extensions.
    """
    try:
        creator_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    # Get user
    user_result = await db.execute(
        select(User).where(User.id == creator_uuid)
    )
    user = user_result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="Creator not found")

    # Get published agents by this creator
    agents_result = await db.execute(
        select(MarketplaceAgent).where(
            or_(
                MarketplaceAgent.created_by_user_id == creator_uuid,
                MarketplaceAgent.forked_by_user_id == creator_uuid
            ),
            MarketplaceAgent.is_published == True,
            MarketplaceAgent.is_active == True
        ).order_by(MarketplaceAgent.downloads.desc())
    )
    agents = agents_result.scalars().all()

    # Calculate total downloads
    total_downloads = sum(agent.downloads or 0 for agent in agents)

    # Calculate average rating
    rated_agents = [a for a in agents if a.rating and a.reviews_count]
    avg_rating = (
        sum(a.rating * a.reviews_count for a in rated_agents) /
        sum(a.reviews_count for a in rated_agents)
        if rated_agents else 5.0
    )

    return {
        "id": str(user.id),
        "name": user.name,
        "username": user.username,
        "avatar_url": user.avatar_url,
        "bio": user.bio,
        "twitter_handle": user.twitter_handle,
        "github_username": user.github_username,
        "website_url": user.website_url,
        "joined_at": user.created_at.isoformat() if user.created_at else None,
        "stats": {
            "extensions_count": len(agents),
            "total_downloads": total_downloads,
            "average_rating": round(avg_rating, 1)
        },
        "extensions": [
            {
                "id": str(agent.id),
                "name": agent.name,
                "slug": agent.slug,
                "description": agent.description,
                "category": agent.category,
                "item_type": agent.item_type or "agent",
                "source_type": agent.source_type or "closed",
                "is_forkable": agent.is_forkable,
                "is_active": agent.is_active,
                "icon": agent.icon,
                "avatar_url": agent.avatar_url,
                "pricing_type": agent.pricing_type,
                "price": agent.price,
                "downloads": agent.downloads or 0,
                "rating": agent.rating or 5.0,
                "reviews_count": agent.reviews_count or 0,
                "usage_count": agent.usage_count or 0,
                "features": agent.features or [],
                "tags": agent.tags or [],
                "is_featured": agent.is_featured
            }
            for agent in agents
        ]
    }


@router.get("/{user_id}/agents")
async def get_creator_agents(
    user_id: str,
    page: int = 1,
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """
    Get paginated list of a creator's published agents.
    """
    try:
        creator_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    offset = (page - 1) * limit

    # Count total
    count_result = await db.execute(
        select(func.count(MarketplaceAgent.id)).where(
            or_(
                MarketplaceAgent.created_by_user_id == creator_uuid,
                MarketplaceAgent.forked_by_user_id == creator_uuid
            ),
            MarketplaceAgent.is_published == True,
            MarketplaceAgent.is_active == True
        )
    )
    total = count_result.scalar() or 0

    # Get paginated agents
    agents_result = await db.execute(
        select(MarketplaceAgent).where(
            or_(
                MarketplaceAgent.created_by_user_id == creator_uuid,
                MarketplaceAgent.forked_by_user_id == creator_uuid
            ),
            MarketplaceAgent.is_published == True,
            MarketplaceAgent.is_active == True
        ).order_by(MarketplaceAgent.downloads.desc())
        .offset(offset)
        .limit(limit)
    )
    agents = agents_result.scalars().all()

    return {
        "agents": [
            {
                "id": str(agent.id),
                "name": agent.name,
                "slug": agent.slug,
                "description": agent.description,
                "category": agent.category,
                "item_type": agent.item_type or "agent",
                "source_type": agent.source_type or "closed",
                "is_forkable": agent.is_forkable,
                "is_active": agent.is_active,
                "icon": agent.icon,
                "avatar_url": agent.avatar_url,
                "pricing_type": agent.pricing_type,
                "price": agent.price,
                "downloads": agent.downloads or 0,
                "rating": agent.rating or 5.0,
                "reviews_count": agent.reviews_count or 0,
                "usage_count": agent.usage_count or 0,
                "features": agent.features or [],
                "tags": agent.tags or [],
                "is_featured": agent.is_featured
            }
            for agent in agents
        ],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit
    }


@router.get("/{user_id}/stats")
async def get_creator_stats(
    user_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get aggregated stats for a creator.
    """
    try:
        creator_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    # Get all agents by this creator
    agents_result = await db.execute(
        select(MarketplaceAgent).where(
            or_(
                MarketplaceAgent.created_by_user_id == creator_uuid,
                MarketplaceAgent.forked_by_user_id == creator_uuid
            ),
            MarketplaceAgent.is_published == True
        )
    )
    agents = agents_result.scalars().all()

    if not agents:
        return {
            "extensions_count": 0,
            "total_downloads": 0,
            "total_usage": 0,
            "average_rating": 5.0,
            "total_reviews": 0
        }

    total_downloads = sum(agent.downloads or 0 for agent in agents)
    total_usage = sum(agent.usage_count or 0 for agent in agents)
    total_reviews = sum(agent.reviews_count or 0 for agent in agents)

    # Calculate weighted average rating
    rated_agents = [a for a in agents if a.rating and a.reviews_count]
    if rated_agents:
        avg_rating = (
            sum(a.rating * a.reviews_count for a in rated_agents) /
            sum(a.reviews_count for a in rated_agents)
        )
    else:
        avg_rating = 5.0

    return {
        "extensions_count": len(agents),
        "total_downloads": total_downloads,
        "total_usage": total_usage,
        "average_rating": round(avg_rating, 1),
        "total_reviews": total_reviews
    }
