from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..database import get_db
from ..models import MarketplaceAgent, User
from ..auth import get_current_active_user

router = APIRouter()

@router.get("/")
async def get_agents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get all active marketplace agents.

    This endpoint now uses MarketplaceAgent (the new factory system).
    All agents go through the unified factory interface.
    """
    result = await db.execute(
        select(MarketplaceAgent).where(
            MarketplaceAgent.is_active == True
        ).order_by(MarketplaceAgent.created_at.asc())
    )
    agents = result.scalars().all()

    # Return simplified response
    return [
        {
            "id": agent.id,
            "name": agent.name,
            "slug": agent.slug,
            "description": agent.description,
            "agent_type": agent.agent_type,
            "mode": agent.mode,  # Deprecated but kept for compatibility
            "icon": agent.icon,
            "category": agent.category
        }
        for agent in agents
    ]


@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get a specific marketplace agent by ID."""
    result = await db.execute(
        select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id)
    )
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return {
        "id": agent.id,
        "name": agent.name,
        "slug": agent.slug,
        "description": agent.description,
        "long_description": agent.long_description,
        "agent_type": agent.agent_type,
        "mode": agent.mode,
        "system_prompt": agent.system_prompt,
        "tools": agent.tools,
        "icon": agent.icon,
        "category": agent.category,
        "features": agent.features,
        "tags": agent.tags
    }


# Note: Create, Update, Delete endpoints removed
# Marketplace agents should be managed through the marketplace system
# For development, create agents directly in the database or via migration scripts
