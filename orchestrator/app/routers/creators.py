"""
Creator/Author profile API endpoints for the marketplace.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import MarketplaceAgent, MarketplaceBase, Theme
from ..models_auth import User
from ..username_validation import normalize_username, validate_username

router = APIRouter(prefix="/api/creators", tags=["creators"])


async def _build_creator_response(user: User, db: AsyncSession) -> dict:
    """Build the public creator profile response dict.

    Shared by UUID and username lookup endpoints.
    """
    # Get published agents by this creator
    agents_result = await db.execute(
        select(MarketplaceAgent)
        .where(
            or_(
                MarketplaceAgent.created_by_user_id == user.id,
                MarketplaceAgent.forked_by_user_id == user.id,
            ),
            MarketplaceAgent.is_published,
            MarketplaceAgent.is_active,
        )
        .order_by(MarketplaceAgent.downloads.desc())
    )
    agents = agents_result.scalars().all()

    # Get published (public) bases by this creator
    bases_result = await db.execute(
        select(MarketplaceBase)
        .where(
            MarketplaceBase.created_by_user_id == user.id,
            MarketplaceBase.visibility == "public",
            MarketplaceBase.is_active,
        )
        .order_by(MarketplaceBase.downloads.desc())
    )
    bases = bases_result.scalars().all()

    # Get published themes by this creator
    themes_result = await db.execute(
        select(Theme)
        .where(
            Theme.created_by_user_id == user.id,
            Theme.is_published,
            Theme.is_active,
        )
        .order_by(Theme.downloads.desc())
    )
    themes = themes_result.scalars().all()

    # Calculate total downloads (agents + bases + themes)
    total_downloads = (
        sum(agent.downloads or 0 for agent in agents)
        + sum(base.downloads or 0 for base in bases)
        + sum(theme.downloads or 0 for theme in themes)
    )

    # Calculate average rating
    rated_agents = [a for a in agents if a.rating and a.reviews_count]
    avg_rating = (
        sum(a.rating * a.reviews_count for a in rated_agents)
        / sum(a.reviews_count for a in rated_agents)
        if rated_agents
        else 5.0
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
            "extensions_count": len(agents) + len(bases) + len(themes),
            "total_downloads": total_downloads,
            "average_rating": round(avg_rating, 1),
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
                "is_featured": agent.is_featured,
            }
            for agent in agents
        ],
        "bases": [
            {
                "id": str(base.id),
                "name": base.name,
                "slug": base.slug,
                "description": base.description,
                "category": base.category,
                "icon": base.icon,
                "pricing_type": base.pricing_type,
                "downloads": base.downloads or 0,
                "rating": base.rating or 5.0,
                "reviews_count": base.reviews_count or 0,
                "features": base.features or [],
                "tech_stack": base.tech_stack or [],
                "tags": base.tags or [],
                "is_featured": base.is_featured,
            }
            for base in bases
        ],
        "themes": [
            {
                # Wave 1.5: theme.id is now a GUID. Continue exposing the
                # slug as ``id`` for frontend / external API parity.
                "id": theme.slug or str(theme.id),
                "name": theme.name,
                "slug": theme.slug,
                "description": theme.description,
                "category": theme.category,
                "icon": theme.icon,
                "mode": theme.mode,
                "pricing_type": theme.pricing_type,
                "downloads": theme.downloads or 0,
                "rating": theme.rating or 5.0,
                "reviews_count": theme.reviews_count or 0,
                "tags": theme.tags or [],
                "is_featured": theme.is_featured,
            }
            for theme in themes
        ],
    }


# ── Username endpoints (declared before /{user_id} catch-all) ────────────


@router.get("/by-username/{username}")
async def get_creator_by_username(username: str, db: AsyncSession = Depends(get_db)):
    """Public profile lookup by @username."""
    normalized = normalize_username(username)
    valid, error = validate_username(normalized)
    if not valid:
        raise HTTPException(status_code=400, detail=error)

    result = await db.execute(select(User).where(func.lower(User.username) == normalized))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Creator not found")

    return await _build_creator_response(user, db)


@router.get("/check-username/{username}")
async def check_username_availability(username: str, db: AsyncSession = Depends(get_db)):
    """Check if a username is available. Returns {available, reason}."""
    normalized = normalize_username(username)
    valid, error = validate_username(normalized)
    if not valid:
        return {"available": False, "reason": error}

    result = await db.execute(select(User.id).where(func.lower(User.username) == normalized))
    existing = result.scalar_one_or_none()
    if existing is not None:
        return {"available": False, "reason": "Username is not available"}

    return {"available": True, "reason": None}


# ── UUID-based endpoints ─────────────────────────────────────────────────


@router.get("/{user_id}")
async def get_creator_profile(user_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get a creator's public profile and their published extensions.
    """
    try:
        creator_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format") from None

    # Get user
    user_result = await db.execute(select(User).where(User.id == creator_uuid))
    user = user_result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="Creator not found")

    return await _build_creator_response(user, db)


@router.get("/{user_id}/agents")
async def get_creator_agents(
    user_id: str, page: int = 1, limit: int = 20, db: AsyncSession = Depends(get_db)
):
    """
    Get paginated list of a creator's published agents.
    """
    try:
        creator_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format") from None

    offset = (page - 1) * limit

    # Count total
    count_result = await db.execute(
        select(func.count(MarketplaceAgent.id)).where(
            or_(
                MarketplaceAgent.created_by_user_id == creator_uuid,
                MarketplaceAgent.forked_by_user_id == creator_uuid,
            ),
            MarketplaceAgent.is_published,
            MarketplaceAgent.is_active,
        )
    )
    total = count_result.scalar() or 0

    # Get paginated agents
    agents_result = await db.execute(
        select(MarketplaceAgent)
        .where(
            or_(
                MarketplaceAgent.created_by_user_id == creator_uuid,
                MarketplaceAgent.forked_by_user_id == creator_uuid,
            ),
            MarketplaceAgent.is_published,
            MarketplaceAgent.is_active,
        )
        .order_by(MarketplaceAgent.downloads.desc())
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
                "is_featured": agent.is_featured,
            }
            for agent in agents
        ],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }


@router.get("/{user_id}/stats")
async def get_creator_stats(user_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get aggregated stats for a creator.
    """
    try:
        creator_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format") from None

    # Get all agents by this creator
    agents_result = await db.execute(
        select(MarketplaceAgent).where(
            or_(
                MarketplaceAgent.created_by_user_id == creator_uuid,
                MarketplaceAgent.forked_by_user_id == creator_uuid,
            ),
            MarketplaceAgent.is_published,
        )
    )
    agents = agents_result.scalars().all()

    # Get all public bases by this creator
    bases_result = await db.execute(
        select(MarketplaceBase).where(
            MarketplaceBase.created_by_user_id == creator_uuid,
            MarketplaceBase.visibility == "public",
            MarketplaceBase.is_active,
        )
    )
    bases = bases_result.scalars().all()

    # Get published themes by this creator
    themes_result = await db.execute(
        select(Theme).where(
            Theme.created_by_user_id == creator_uuid,
            Theme.is_published,
            Theme.is_active,
        )
    )
    themes = themes_result.scalars().all()

    if not agents and not bases and not themes:
        return {
            "extensions_count": 0,
            "bases_count": 0,
            "themes_count": 0,
            "total_downloads": 0,
            "total_usage": 0,
            "average_rating": 5.0,
            "total_reviews": 0,
        }

    total_downloads = (
        sum(agent.downloads or 0 for agent in agents)
        + sum(base.downloads or 0 for base in bases)
        + sum(theme.downloads or 0 for theme in themes)
    )
    total_usage = sum(agent.usage_count or 0 for agent in agents)
    total_reviews = (
        sum(agent.reviews_count or 0 for agent in agents)
        + sum(base.reviews_count or 0 for base in bases)
        + sum(theme.reviews_count or 0 for theme in themes)
    )

    # Calculate weighted average rating
    rated_agents = [a for a in agents if a.rating and a.reviews_count]
    if rated_agents:
        avg_rating = sum(a.rating * a.reviews_count for a in rated_agents) / sum(
            a.reviews_count for a in rated_agents
        )
    else:
        avg_rating = 5.0

    return {
        "extensions_count": len(agents),
        "bases_count": len(bases),
        "themes_count": len(themes),
        "total_downloads": total_downloads,
        "total_usage": total_usage,
        "average_rating": round(avg_rating, 1),
        "total_reviews": total_reviews,
    }
