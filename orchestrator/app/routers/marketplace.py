"""
Marketplace API endpoints for browsing, purchasing, and managing agents.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timezone
import logging

from ..database import get_db
from ..auth import get_current_active_user
from ..models import (
    User, MarketplaceAgent, UserPurchasedAgent,
    ProjectAgent, AgentReview, Project
)
from ..schemas import MarketplaceAgentResponse, AgentPurchaseRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/marketplace", tags=["marketplace"])


# ============================================================================
# Browse Marketplace
# ============================================================================

@router.get("/agents")
async def get_marketplace_agents(
    category: Optional[str] = None,
    pricing_type: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = Query(default="featured", regex="^(featured|popular|newest|price_asc|price_desc)$"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=12, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Browse marketplace agents with filtering and sorting.
    """
    # Base query
    query = select(MarketplaceAgent).where(MarketplaceAgent.is_active == True)

    # Apply filters
    if category:
        query = query.where(MarketplaceAgent.category == category)

    if pricing_type:
        query = query.where(MarketplaceAgent.pricing_type == pricing_type)

    if search:
        search_filter = f"%{search}%"
        query = query.where(
            func.lower(MarketplaceAgent.name).like(func.lower(search_filter)) |
            func.lower(MarketplaceAgent.description).like(func.lower(search_filter)) |
            func.lower(MarketplaceAgent.tags).like(func.lower(search_filter))
        )

    # Apply sorting
    if sort == "featured":
        query = query.order_by(MarketplaceAgent.is_featured.desc(), MarketplaceAgent.downloads.desc())
    elif sort == "popular":
        query = query.order_by(MarketplaceAgent.downloads.desc())
    elif sort == "newest":
        query = query.order_by(MarketplaceAgent.created_at.desc())
    elif sort == "price_asc":
        query = query.order_by(MarketplaceAgent.price.asc())
    elif sort == "price_desc":
        query = query.order_by(MarketplaceAgent.price.desc())

    # Pagination
    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit)

    # Execute query
    result = await db.execute(query)
    agents = result.scalars().all()

    # Get user's purchased agents
    purchased_result = await db.execute(
        select(UserPurchasedAgent.agent_id).where(
            UserPurchasedAgent.user_id == current_user.id,
            UserPurchasedAgent.is_active == True
        )
    )
    purchased_agent_ids = [row[0] for row in purchased_result.fetchall()]

    # Format response
    response = []
    for agent in agents:
        agent_dict = {
            "id": agent.id,
            "name": agent.name,
            "slug": agent.slug,
            "description": agent.description,
            "category": agent.category,
            "mode": agent.mode,
            "icon": agent.icon,
            "pricing_type": agent.pricing_type,
            "price": agent.price / 100.0 if agent.price else 0,  # Convert cents to dollars
            "downloads": agent.downloads,
            "rating": agent.rating,
            "reviews_count": agent.reviews_count,
            "features": agent.features,
            "tags": agent.tags,
            "is_featured": agent.is_featured,
            "is_purchased": agent.id in purchased_agent_ids
        }
        response.append(agent_dict)

    return {
        "agents": response,
        "page": page,
        "limit": limit,
        "has_more": len(agents) == limit
    }


@router.get("/agents/{slug}")
async def get_agent_details(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get detailed information about a specific agent.
    """
    # Get agent
    result = await db.execute(
        select(MarketplaceAgent).where(MarketplaceAgent.slug == slug)
    )
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Check if user has purchased this agent
    purchased_result = await db.execute(
        select(UserPurchasedAgent).where(
            UserPurchasedAgent.user_id == current_user.id,
            UserPurchasedAgent.agent_id == agent.id,
            UserPurchasedAgent.is_active == True
        )
    )
    is_purchased = purchased_result.scalar_one_or_none() is not None

    # Get recent reviews
    reviews_result = await db.execute(
        select(AgentReview).where(AgentReview.agent_id == agent.id)
        .order_by(AgentReview.created_at.desc())
        .limit(5)
    )
    reviews = reviews_result.scalars().all()

    # Format response
    return {
        "id": agent.id,
        "name": agent.name,
        "slug": agent.slug,
        "description": agent.description,
        "long_description": agent.long_description,
        "category": agent.category,
        "mode": agent.mode,
        "icon": agent.icon,
        "preview_image": agent.preview_image,
        "pricing_type": agent.pricing_type,
        "price": agent.price / 100.0 if agent.price else 0,
        "downloads": agent.downloads,
        "rating": agent.rating,
        "reviews_count": agent.reviews_count,
        "features": agent.features,
        "required_models": agent.required_models,
        "tags": agent.tags,
        "is_featured": agent.is_featured,
        "is_purchased": is_purchased,
        "reviews": [
            {
                "id": review.id,
                "rating": review.rating,
                "comment": review.comment,
                "created_at": review.created_at.isoformat()
            }
            for review in reviews
        ]
    }


# ============================================================================
# Purchase/Add Agents
# ============================================================================

@router.post("/agents/{agent_id}/purchase")
async def purchase_agent(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Purchase or add a free agent to user's library.
    For paid agents, this initiates the Stripe checkout process.
    """
    # Get agent
    result = await db.execute(
        select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id)
    )
    agent = result.scalar_one_or_none()

    if not agent or not agent.is_active:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Check if already purchased
    existing_result = await db.execute(
        select(UserPurchasedAgent).where(
            UserPurchasedAgent.user_id == current_user.id,
            UserPurchasedAgent.agent_id == agent_id
        )
    )
    existing_purchase = existing_result.scalar_one_or_none()

    if existing_purchase and existing_purchase.is_active:
        return {"message": "Agent already in your library", "agent_id": agent_id}

    # Handle free agents
    if agent.pricing_type == "free":
        if existing_purchase:
            # Reactivate existing purchase
            existing_purchase.is_active = True
            existing_purchase.purchase_date = datetime.now(timezone.utc)
        else:
            # Create new purchase record
            purchase = UserPurchasedAgent(
                user_id=current_user.id,
                agent_id=agent_id,
                purchase_type="free",
                is_active=True
            )
            db.add(purchase)

        # Update download count
        agent.downloads += 1

        await db.commit()

        return {
            "message": "Free agent added to your library",
            "agent_id": agent_id,
            "success": True
        }

    # For paid agents, create Stripe checkout session
    # This will be implemented when we add the Stripe service
    from ..services.stripe_service import StripeService

    stripe_service = StripeService()

    # Create checkout session
    success_url = f"http://studio.localhost/marketplace/success?agent={agent.slug}"
    cancel_url = f"http://studio.localhost/marketplace/agent/{agent.slug}"

    try:
        session = await stripe_service.create_checkout_session(
            user=current_user,
            agent=agent,
            success_url=success_url,
            cancel_url=cancel_url,
            db=db
        )

        return {
            "checkout_url": session['url'] if isinstance(session, dict) else session.url,
            "session_id": session['id'] if isinstance(session, dict) else session.id,
            "agent_id": agent_id
        }
    except Exception as e:
        logger.error(f"Failed to create Stripe checkout: {e}")
        raise HTTPException(status_code=500, detail="Failed to create checkout session")


@router.get("/my-agents")
async def get_user_agents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get all agents in the user's library.
    """
    # Query user's purchased agents
    result = await db.execute(
        select(MarketplaceAgent, UserPurchasedAgent)
        .join(UserPurchasedAgent, UserPurchasedAgent.agent_id == MarketplaceAgent.id)
        .where(
            UserPurchasedAgent.user_id == current_user.id,
            UserPurchasedAgent.is_active == True
        )
        .order_by(UserPurchasedAgent.purchase_date.desc())
    )

    agents_data = result.fetchall()

    response = []
    for agent, purchase in agents_data:
        response.append({
            "id": agent.id,
            "name": agent.name,
            "slug": agent.slug,
            "description": agent.description,
            "category": agent.category,
            "mode": agent.mode,
            "icon": agent.icon,
            "pricing_type": agent.pricing_type,
            "features": agent.features,
            "purchase_date": purchase.purchase_date.isoformat(),
            "purchase_type": purchase.purchase_type,
            "expires_at": purchase.expires_at.isoformat() if purchase.expires_at else None
        })

    return {"agents": response}


# ============================================================================
# Project Agent Management
# ============================================================================

@router.get("/projects/{project_id}/available-agents")
async def get_available_agents_for_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get agents that the user owns and can add to this project.
    """
    # Verify project ownership
    project_result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == current_user.id
        )
    )
    project = project_result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get user's purchased agents
    purchased_result = await db.execute(
        select(MarketplaceAgent, UserPurchasedAgent)
        .join(UserPurchasedAgent, UserPurchasedAgent.agent_id == MarketplaceAgent.id)
        .where(
            UserPurchasedAgent.user_id == current_user.id,
            UserPurchasedAgent.is_active == True
        )
    )
    purchased_agents = purchased_result.fetchall()

    # Get agents already added to this project
    project_agents_result = await db.execute(
        select(ProjectAgent.agent_id).where(
            ProjectAgent.project_id == project_id,
            ProjectAgent.enabled == True
        )
    )
    project_agent_ids = [row[0] for row in project_agents_result.fetchall()]

    # Filter out agents already in project
    available_agents = []
    for agent, purchase in purchased_agents:
        if agent.id not in project_agent_ids:
            available_agents.append({
                "id": agent.id,
                "name": agent.name,
                "slug": agent.slug,
                "description": agent.description,
                "category": agent.category,
                "mode": agent.mode,
                "icon": agent.icon,
                "features": agent.features
            })

    return {"available_agents": available_agents}


@router.post("/projects/{project_id}/agents/{agent_id}")
async def add_agent_to_project(
    project_id: int,
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Add an agent from user's library to a project.
    """
    # Verify project ownership
    project_result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == current_user.id
        )
    )
    project = project_result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Verify user owns the agent
    purchase_result = await db.execute(
        select(UserPurchasedAgent).where(
            UserPurchasedAgent.user_id == current_user.id,
            UserPurchasedAgent.agent_id == agent_id,
            UserPurchasedAgent.is_active == True
        )
    )
    purchase = purchase_result.scalar_one_or_none()

    if not purchase:
        raise HTTPException(status_code=403, detail="You don't own this agent")

    # Check if agent is already in project
    existing_result = await db.execute(
        select(ProjectAgent).where(
            ProjectAgent.project_id == project_id,
            ProjectAgent.agent_id == agent_id
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        if existing.enabled:
            return {"message": "Agent already active in project"}
        else:
            # Re-enable the agent
            existing.enabled = True
            existing.added_at = datetime.now(timezone.utc)
    else:
        # Add agent to project
        project_agent = ProjectAgent(
            project_id=project_id,
            agent_id=agent_id,
            user_id=current_user.id,
            enabled=True
        )
        db.add(project_agent)

    await db.commit()

    return {"message": "Agent added to project", "project_id": project_id, "agent_id": agent_id}


@router.delete("/projects/{project_id}/agents/{agent_id}")
async def remove_agent_from_project(
    project_id: int,
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Remove an agent from a project.
    """
    # Verify project ownership
    project_result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == current_user.id
        )
    )
    project = project_result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Find and disable the agent
    result = await db.execute(
        select(ProjectAgent).where(
            ProjectAgent.project_id == project_id,
            ProjectAgent.agent_id == agent_id,
            ProjectAgent.user_id == current_user.id
        )
    )
    project_agent = result.scalar_one_or_none()

    if not project_agent:
        raise HTTPException(status_code=404, detail="Agent not found in project")

    project_agent.enabled = False
    await db.commit()

    return {"message": "Agent removed from project"}


@router.get("/projects/{project_id}/agents")
async def get_project_agents(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get all active agents for a project.
    """
    # Verify project ownership
    project_result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == current_user.id
        )
    )
    project = project_result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get project's agents
    result = await db.execute(
        select(MarketplaceAgent, ProjectAgent)
        .join(ProjectAgent, ProjectAgent.agent_id == MarketplaceAgent.id)
        .where(
            ProjectAgent.project_id == project_id,
            ProjectAgent.enabled == True
        )
        .order_by(ProjectAgent.added_at.desc())
    )

    agents_data = result.fetchall()

    response = []
    for agent, project_agent in agents_data:
        response.append({
            "id": agent.id,
            "name": agent.name,
            "slug": agent.slug,
            "description": agent.description,
            "category": agent.category,
            "mode": agent.mode,
            "icon": agent.icon,
            "system_prompt": agent.system_prompt,  # Include for actual usage
            "features": agent.features,
            "added_at": project_agent.added_at.isoformat()
        })

    return {"agents": response}


# ============================================================================
# Reviews
# ============================================================================

@router.post("/agents/{agent_id}/review")
async def create_agent_review(
    agent_id: int,
    rating: int = Query(ge=1, le=5),
    comment: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Create or update a review for an agent.
    """
    # Verify user owns the agent
    purchase_result = await db.execute(
        select(UserPurchasedAgent).where(
            UserPurchasedAgent.user_id == current_user.id,
            UserPurchasedAgent.agent_id == agent_id,
            UserPurchasedAgent.is_active == True
        )
    )
    purchase = purchase_result.scalar_one_or_none()

    if not purchase:
        raise HTTPException(status_code=403, detail="You must own this agent to review it")

    # Check for existing review
    existing_result = await db.execute(
        select(AgentReview).where(
            AgentReview.user_id == current_user.id,
            AgentReview.agent_id == agent_id
        )
    )
    existing_review = existing_result.scalar_one_or_none()

    if existing_review:
        # Update existing review
        existing_review.rating = rating
        existing_review.comment = comment
        existing_review.created_at = datetime.now(timezone.utc)
    else:
        # Create new review
        review = AgentReview(
            agent_id=agent_id,
            user_id=current_user.id,
            rating=rating,
            comment=comment
        )
        db.add(review)

    # Update agent's average rating
    rating_result = await db.execute(
        select(func.avg(AgentReview.rating), func.count(AgentReview.id))
        .where(AgentReview.agent_id == agent_id)
    )
    avg_rating, review_count = rating_result.one()

    agent_result = await db.execute(
        select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id)
    )
    agent = agent_result.scalar_one()
    agent.rating = float(avg_rating) if avg_rating else 5.0
    agent.reviews_count = review_count

    await db.commit()

    return {"message": "Review submitted successfully", "rating": rating}