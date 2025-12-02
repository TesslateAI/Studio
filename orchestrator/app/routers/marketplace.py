"""
Marketplace API endpoints for browsing, purchasing, and managing agents.
"""

from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status, Body, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
import logging

from ..database import get_db
from ..models import (
    User, MarketplaceAgent, UserPurchasedAgent,
    ProjectAgent, AgentReview, Project,
    MarketplaceBase, UserPurchasedBase, BaseReview
)
from ..schemas import MarketplaceAgentResponse, AgentPurchaseRequest

logger = logging.getLogger(__name__)
router = APIRouter()

from ..config import get_settings
from ..users import current_active_user, current_superuser
settings = get_settings()


# ============================================================================
# Models Configuration
# ============================================================================

@router.get("/models")
async def get_available_models(
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get list of available models from LiteLLM with pricing information.
    Includes both system models and models from user's configured providers.
    Returns models that users can select for open source agents.
    """
    from ..services.litellm_service import litellm_service
    from ..models import UserAPIKey, UserCustomModel

    # Get models from LiteLLM
    litellm_models = await litellm_service.get_available_models()

    # Model pricing database (approximate, in USD per 1M tokens)
    # These are typical costs - actual costs may vary
    model_pricing = {
        # OpenAI
        "gpt-4": {"input": 30.0, "output": 60.0},
        "gpt-4-turbo": {"input": 10.0, "output": 30.0},
        "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},

        # Anthropic
        "claude-3-opus": {"input": 15.0, "output": 75.0},
        "claude-3-sonnet": {"input": 3.0, "output": 15.0},
        "claude-3-haiku": {"input": 0.25, "output": 1.25},

        # Open source / self-hosted
        "llama-3.3": {"input": 0.0, "output": 0.0},
        "qwen": {"input": 0.0, "output": 0.0},
        "default": {"input": 2.0, "output": 6.0}  # Default for unknown models
    }

    def get_model_pricing(model_id: str):
        """Get pricing for a model based on ID"""
        model_lower = model_id.lower()
        for key, price in model_pricing.items():
            if key in model_lower:
                return price
        return model_pricing["default"]

    # Convert LiteLLM models to response format with pricing
    system_models = [
        {
            "id": model.get('id'),
            "name": model.get('id'),
            "source": "system",
            "provider": "internal",
            "pricing": get_model_pricing(model.get('id', '')),
            "available": True
        }
        for model in litellm_models if model.get('id')
    ]

    # Check which providers the user has API keys for
    user_keys_query = select(UserAPIKey).where(
        UserAPIKey.user_id == current_user.id,
        UserAPIKey.is_active == True
    )
    result = await db.execute(user_keys_query)
    user_keys = result.scalars().all()

    # Map of providers user has keys for
    user_providers = {key.provider for key in user_keys}

    # Get user's custom models
    custom_models_query = select(UserCustomModel).where(
        UserCustomModel.user_id == current_user.id,
        UserCustomModel.is_active == True
    )
    result = await db.execute(custom_models_query)
    custom_models = result.scalars().all()

    # Convert custom models to response format
    custom_models_data = [
        {
            "id": model.model_id,
            "name": model.model_name,
            "source": "custom",
            "provider": model.provider,
            "pricing": {
                "input": model.pricing_input or 0.0,
                "output": model.pricing_output or 0.0
            },
            "available": True,
            "custom_id": model.id
        }
        for model in custom_models
    ]

    # Add information about available external providers
    external_providers = [
        {
            "provider": "openrouter",
            "name": "OpenRouter",
            "description": "Access 200+ models through OpenRouter",
            "has_key": "openrouter" in user_providers,
            "setup_required": "openrouter" not in user_providers,
            "models_count": "200+"
        }
    ]

    # Fallback to config if LiteLLM call fails
    if not system_models:
        models_str = settings.litellm_default_models
        system_models = [
            {
                "id": m.strip(),
                "name": m.strip(),
                "source": "system",
                "provider": "internal",
                "pricing": get_model_pricing(m.strip()),
                "available": True
            }
            for m in models_str.split(",") if m.strip()
        ]

    # Combine system models and custom models
    all_models = system_models + custom_models_data

    return {
        "models": all_models,
        "default": system_models[0]["id"] if system_models else None,
        "count": len(all_models),
        "external_providers": external_providers,
        "user_providers": list(user_providers),
        "custom_models": custom_models_data
    }


@router.post("/models/custom")
async def add_custom_model(
    model_id: str = Body(...),
    model_name: str = Body(...),
    pricing_input: Optional[float] = Body(None),
    pricing_output: Optional[float] = Body(None),
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Add a custom OpenRouter model to the user's account.
    """
    from ..models import UserCustomModel

    # Check if model already exists for this user
    existing_query = select(UserCustomModel).where(
        UserCustomModel.user_id == current_user.id,
        UserCustomModel.model_id == model_id,
        UserCustomModel.is_active == True
    )
    result = await db.execute(existing_query)
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(status_code=400, detail="Model already exists in your library")

    # Create new custom model
    custom_model = UserCustomModel(
        user_id=current_user.id,
        model_id=model_id,
        model_name=model_name,
        provider="openrouter",
        pricing_input=pricing_input,
        pricing_output=pricing_output
    )

    db.add(custom_model)
    await db.commit()
    await db.refresh(custom_model)

    return {
        "message": "Custom model added successfully",
        "model": {
            "id": custom_model.model_id,
            "name": custom_model.model_name,
            "source": "custom",
            "provider": custom_model.provider,
            "pricing": {
                "input": custom_model.pricing_input or 0.0,
                "output": custom_model.pricing_output or 0.0
            },
            "custom_id": custom_model.id
        }
    }


@router.delete("/models/custom/{model_id}")
async def delete_custom_model(
    model_id: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a custom model from the user's account.
    """
    from ..models import UserCustomModel

    # Find the model
    query = select(UserCustomModel).where(
        UserCustomModel.id == model_id,
        UserCustomModel.user_id == current_user.id
    )
    result = await db.execute(query)
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(status_code=404, detail="Custom model not found")

    # Soft delete
    model.is_active = False
    await db.commit()

    return {
        "message": "Custom model deleted successfully",
        "success": True
    }


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
    current_user: User = Depends(current_active_user)
):
    """
    Browse marketplace agents with filtering and sorting.
    Shows official Tesslate agents and published community agents.
    """
    # Base query - show official agents AND published community agents
    query = select(MarketplaceAgent).options(
        selectinload(MarketplaceAgent.forked_by_user)
    ).where(
        MarketplaceAgent.is_active == True,
        (MarketplaceAgent.forked_by_user_id == None) | (MarketplaceAgent.is_published == True)
    )

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
        # Determine creator info
        creator_type = "official"  # Tesslate
        creator_name = "Tesslate"

        if agent.forked_by_user_id:
            creator_type = "community"
            # Get creator's name
            if agent.forked_by_user:
                creator_name = agent.forked_by_user.email.split('@')[0]  # Use email username as display name

        agent_dict = {
            "id": agent.id,
            "name": agent.name,
            "slug": agent.slug,
            "description": agent.description,
            "long_description": agent.long_description,
            "category": agent.category,
            "item_type": agent.item_type,
            "mode": agent.mode,
            "agent_type": agent.agent_type,  # StreamAgent, IterativeAgent, etc.
            "model": agent.model,
            "source_type": agent.source_type,
            "is_forkable": agent.is_forkable,
            "is_active": agent.is_active,
            "icon": agent.icon,
            "avatar_url": agent.avatar_url,  # Custom logo/profile picture
            "pricing_type": agent.pricing_type,
            "price": agent.price / 100.0 if agent.price else 0,  # Convert cents to dollars
            "usage_count": agent.usage_count or 0,  # Number of messages sent to this agent
            "downloads": agent.downloads,
            "rating": agent.rating,
            "reviews_count": agent.reviews_count,
            "features": agent.features,
            "tags": agent.tags,
            "is_featured": agent.is_featured,
            "is_purchased": agent.id in purchased_agent_ids,
            "creator_type": creator_type,  # "official" or "community"
            "creator_name": creator_name  # "Tesslate" or username
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
    current_user: User = Depends(current_active_user)
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
        "agent_type": agent.agent_type,  # StreamAgent, IterativeAgent, etc.
        "system_prompt": agent.system_prompt,  # Include system prompt for forking
        "model": agent.model,
        "icon": agent.icon,
        "avatar_url": agent.avatar_url,  # Custom logo/profile picture
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
        "is_forkable": agent.is_forkable,
        "source_type": agent.source_type,
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
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
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
    from ..services.stripe_service import stripe_service

    # Create checkout session with origin-based URLs to preserve user's domain
    # This ensures localStorage and cookies work correctly after Stripe redirect
    origin = request.headers.get('origin') or request.headers.get('referer', '').rstrip('/').split('?')[0].rsplit('/', 1)[0] or settings.get_app_base_url
    success_url = f"{origin}/marketplace/success?agent={agent.slug}&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/marketplace/agent/{agent.slug}"

    try:
        session = await stripe_service.create_agent_purchase_checkout(
            user=current_user,
            agent=agent,
            success_url=success_url,
            cancel_url=cancel_url,
            db=db
        )

        if not session:
            raise HTTPException(
                status_code=500,
                detail="Stripe not configured or checkout creation failed"
            )

        return {
            "checkout_url": session['url'] if isinstance(session, dict) else session.url,
            "session_id": session['id'] if isinstance(session, dict) else session.id,
            "agent_id": agent_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create Stripe checkout: {e}")
        raise HTTPException(status_code=500, detail="Failed to create checkout session")


@router.post("/verify-purchase")
async def verify_agent_purchase(
    session_id: str = Body(..., embed=True),
    agent_slug: Optional[str] = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
):
    """
    Verify a Stripe checkout session and add the agent to the user's library.
    Called after successful checkout redirect.
    """
    from ..services.stripe_service import stripe_service
    import stripe as stripe_lib

    if not stripe_service.stripe:
        raise HTTPException(status_code=500, detail="Stripe not configured")

    try:
        # Retrieve the checkout session from Stripe
        session = stripe_lib.checkout.Session.retrieve(
            session_id,
            expand=['line_items', 'subscription']
        )

        # Verify session is complete
        if session.payment_status != 'paid':
            raise HTTPException(
                status_code=400,
                detail="Payment not completed"
            )

        # Verify the customer matches the current user
        user_billing = await db.execute(
            select(User).where(User.id == current_user.id)
        )
        user = user_billing.scalar_one()

        if not user.stripe_customer_id or user.stripe_customer_id != session.customer:
            raise HTTPException(
                status_code=403,
                detail="Session customer does not match user"
            )

        # Get agent from metadata or slug parameter
        agent_id_from_metadata = session.metadata.get('agent_id') if session.metadata else None

        # Try to find agent by ID from metadata or by slug
        query = select(MarketplaceAgent)
        if agent_id_from_metadata:
            query = query.where(MarketplaceAgent.id == agent_id_from_metadata)
        elif agent_slug:
            query = query.where(MarketplaceAgent.slug == agent_slug)
        else:
            raise HTTPException(status_code=400, detail="No agent identifier provided")

        result = await db.execute(query)
        agent = result.scalar_one_or_none()

        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Check if user already has this agent
        existing_query = select(UserPurchasedAgent).where(
            and_(
                UserPurchasedAgent.user_id == current_user.id,
                UserPurchasedAgent.agent_id == agent.id
            )
        )
        existing_result = await db.execute(existing_query)
        existing_purchase = existing_result.scalar_one_or_none()

        if existing_purchase:
            # Update existing purchase with new subscription ID
            existing_purchase.stripe_subscription_id = session.subscription.id if session.subscription else None
            existing_purchase.stripe_payment_intent = session.payment_intent
            existing_purchase.is_active = True
            existing_purchase.purchase_date = datetime.now(timezone.utc)

            if session.subscription:
                # Subscription - set expires_at to None (ongoing)
                existing_purchase.expires_at = None
                existing_purchase.purchase_type = "monthly"
            else:
                # One-time payment - set expiration if applicable
                existing_purchase.purchase_type = "one_time"
        else:
            # Create new purchase record
            new_purchase = UserPurchasedAgent(
                user_id=current_user.id,
                agent_id=agent.id,
                stripe_payment_intent=session.payment_intent,
                stripe_subscription_id=session.subscription.id if session.subscription else None,
                purchase_type="monthly" if session.subscription else "one_time",
                purchase_date=datetime.now(timezone.utc),
                is_active=True,
                expires_at=None if session.subscription else None,  # Subscriptions don't expire until cancelled
                selected_model=agent.model
            )
            db.add(new_purchase)

        # Update agent download count
        agent.downloads += 1

        await db.commit()

        return {
            "success": True,
            "message": "Agent added to your library",
            "agent_id": str(agent.id),
            "agent_name": agent.name
        }

    except stripe_lib.error.StripeError as e:
        logger.error(f"Stripe error during purchase verification: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to verify payment: {str(e)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to verify purchase: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to verify purchase"
        )


@router.get("/subscriptions")
async def get_user_subscriptions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
):
    """
    Get all active agent subscriptions and purchases for the current user.
    Returns both one-time purchases and recurring subscriptions.
    """
    # Get all active purchased agents (both one-time and subscriptions)
    query = select(UserPurchasedAgent, MarketplaceAgent).join(
        MarketplaceAgent,
        UserPurchasedAgent.agent_id == MarketplaceAgent.id
    ).where(
        and_(
            UserPurchasedAgent.user_id == current_user.id,
            UserPurchasedAgent.is_active == True
        )
    )

    result = await db.execute(query)
    purchases = result.all()

    from ..services.stripe_service import stripe_service
    import stripe as stripe_lib

    subscriptions = []
    for purchase, agent in purchases:
        subscription_data = {
            "id": str(purchase.id),
            "agent_id": str(agent.id),
            "name": agent.name,
            "slug": agent.slug,
            "icon": agent.icon,
            "price": agent.price,
            "purchase_type": purchase.purchase_type,  # "onetime" or "monthly"
            "subscription_id": purchase.stripe_subscription_id,
            "purchase_date": purchase.purchase_date.isoformat(),
            "expires_at": purchase.expires_at.isoformat() if purchase.expires_at else None,
            "is_active": purchase.is_active,
            "cancel_at_period_end": False,
            "current_period_end": None,
            "cancel_at": None
        }

        # If it's a monthly subscription, fetch cancellation info from Stripe
        # Check for both "monthly" and "subscription" (legacy naming)
        if purchase.purchase_type in ("monthly", "subscription") and purchase.stripe_subscription_id and stripe_service.stripe:
            try:
                from datetime import datetime
                logger.info(f"DEBUG: Fetching Stripe subscription for {purchase.stripe_subscription_id}, purchase_type={purchase.purchase_type}")
                stripe_sub = stripe_lib.Subscription.retrieve(purchase.stripe_subscription_id)

                # Get cancellation status
                subscription_data["cancel_at_period_end"] = stripe_sub.cancel_at_period_end
                logger.info(f"DEBUG: Stripe subscription {purchase.stripe_subscription_id} cancel_at_period_end={stripe_sub.cancel_at_period_end}")

                # Get current period end (when subscription renews or ends)
                # Try both dictionary and attribute access for compatibility
                try:
                    period_end = stripe_sub.get('current_period_end') if hasattr(stripe_sub, 'get') else stripe_sub.current_period_end
                    if period_end:
                        subscription_data["current_period_end"] = datetime.fromtimestamp(period_end).isoformat()
                        logger.info(f"DEBUG: current_period_end={subscription_data['current_period_end']}")
                except (AttributeError, KeyError) as e:
                    logger.warning(f"Could not get current_period_end for {purchase.stripe_subscription_id}: {e}")

                # Get cancel_at if subscription is set to cancel at specific time
                try:
                    cancel_at = stripe_sub.get('cancel_at') if hasattr(stripe_sub, 'get') else stripe_sub.cancel_at
                    if cancel_at:
                        subscription_data["cancel_at"] = datetime.fromtimestamp(cancel_at).isoformat()
                except (AttributeError, KeyError):
                    pass  # cancel_at is optional

            except Exception as e:
                logger.warning(f"Failed to fetch Stripe subscription details for {purchase.stripe_subscription_id}: {e}")
        else:
            logger.info(f"DEBUG: Skipping Stripe fetch for {agent.name}: purchase_type={purchase.purchase_type}, has_subscription_id={purchase.stripe_subscription_id is not None}, stripe_enabled={stripe_service.stripe is not None}")

        subscriptions.append(subscription_data)

    return subscriptions


@router.post("/subscriptions/{subscription_id}/cancel")
async def cancel_agent_subscription(
    subscription_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
):
    """
    Cancel an agent subscription.
    """
    from ..services.stripe_service import stripe_service
    import stripe as stripe_lib

    logger.info(f"DEBUG: Cancel agent subscription request - subscription_id: {subscription_id}, user_id: {current_user.id}")

    if not stripe_service.stripe:
        logger.error("DEBUG: Stripe not configured")
        raise HTTPException(status_code=500, detail="Stripe not configured")

    try:
        # Find the purchase record with this subscription ID
        query = select(UserPurchasedAgent).where(
            and_(
                UserPurchasedAgent.user_id == current_user.id,
                UserPurchasedAgent.stripe_subscription_id == subscription_id
            )
        )
        result = await db.execute(query)
        purchase = result.scalar_one_or_none()

        logger.info(f"DEBUG: Purchase record found: {purchase is not None}")
        if purchase:
            logger.info(f"DEBUG: Purchase details - id: {purchase.id}, agent_id: {purchase.agent_id}, stripe_subscription_id: {purchase.stripe_subscription_id}")

        if not purchase:
            logger.error(f"DEBUG: Subscription not found for subscription_id: {subscription_id}, user_id: {current_user.id}")
            raise HTTPException(status_code=404, detail="Subscription not found")

        # Cancel the subscription in Stripe
        subscription = stripe_lib.Subscription.modify(
            subscription_id,
            cancel_at_period_end=True
        )

        logger.info(f"Cancelled agent subscription {subscription_id} for user {current_user.id}")

        return {
            "success": True,
            "message": "Subscription will be cancelled at the end of the billing period",
            "cancel_at": subscription.cancel_at
        }

    except stripe_lib.error.StripeError as e:
        logger.error(f"Stripe error during subscription cancellation: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to cancel subscription: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Failed to cancel subscription: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to cancel subscription"
        )


@router.post("/subscriptions/{subscription_id}/renew")
async def renew_agent_subscription(
    subscription_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
):
    """
    Renew a cancelled agent subscription (reactivate before it ends).
    """
    from ..services.stripe_service import stripe_service
    import stripe as stripe_lib

    logger.info(f"DEBUG: Renew agent subscription request - subscription_id: {subscription_id}, user_id: {current_user.id}")

    if not stripe_service.stripe:
        logger.error("DEBUG: Stripe not configured")
        raise HTTPException(status_code=500, detail="Stripe not configured")

    try:
        # Find the purchase record with this subscription ID
        query = select(UserPurchasedAgent).where(
            and_(
                UserPurchasedAgent.user_id == current_user.id,
                UserPurchasedAgent.stripe_subscription_id == subscription_id
            )
        )
        result = await db.execute(query)
        purchase = result.scalar_one_or_none()

        logger.info(f"DEBUG: Purchase record found: {purchase is not None}")
        if purchase:
            logger.info(f"DEBUG: Purchase details - id: {purchase.id}, agent_id: {purchase.agent_id}, stripe_subscription_id: {purchase.stripe_subscription_id}")

        if not purchase:
            logger.error(f"DEBUG: Subscription not found for subscription_id: {subscription_id}, user_id: {current_user.id}")
            raise HTTPException(status_code=404, detail="Subscription not found")

        # Reactivate the subscription in Stripe by setting cancel_at_period_end to False
        subscription = stripe_lib.Subscription.modify(
            subscription_id,
            cancel_at_period_end=False
        )

        logger.info(f"Renewed agent subscription {subscription_id} for user {current_user.id}")

        return {
            "success": True,
            "message": "Subscription has been renewed and will continue after the current period"
        }

    except stripe_lib.error.StripeError as e:
        logger.error(f"Stripe error during subscription renewal: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to renew subscription: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Failed to renew subscription: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to renew subscription"
        )


@router.post("/agents/{agent_id}/fork")
async def fork_agent(
    agent_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
):
    """
    Fork an open source agent to create a custom version with optional customizations.
    """
    # Get the parent agent
    result = await db.execute(
        select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id)
    )
    parent_agent = result.scalar_one_or_none()

    if not parent_agent or not parent_agent.is_active:
        raise HTTPException(status_code=404, detail="Agent not found")

    if not parent_agent.is_forkable:
        raise HTTPException(status_code=403, detail="This agent cannot be forked")

    # Create a forked agent
    forked_slug = f"{parent_agent.slug}-fork-{current_user.id}-{datetime.now(timezone.utc).timestamp()}"

    forked_agent = MarketplaceAgent(
        name=name or f"{parent_agent.name} (My Fork)",
        slug=forked_slug,
        description=description or parent_agent.description,
        long_description=parent_agent.long_description,
        category=parent_agent.category,
        item_type=parent_agent.item_type,
        system_prompt=system_prompt or parent_agent.system_prompt,
        mode=parent_agent.mode,
        agent_type=parent_agent.agent_type,
        tools=parent_agent.tools,
        model=model or parent_agent.model,
        is_forkable=False,  # Forked agents can't be forked again
        parent_agent_id=parent_agent.id,
        forked_by_user_id=current_user.id,
        config={},  # User can customize this later
        icon=parent_agent.icon,
        preview_image=parent_agent.preview_image,
        pricing_type="free",
        price=0,
        source_type="open",
        requires_user_keys=parent_agent.requires_user_keys,
        downloads=0,
        rating=5.0,
        reviews_count=0,
        features=parent_agent.features,
        required_models=[model] if model else parent_agent.required_models,
        tags=parent_agent.tags,
        is_featured=False,
        is_active=True,
        is_published=False  # Not published to marketplace by default
    )

    db.add(forked_agent)
    await db.commit()
    await db.refresh(forked_agent)

    # Automatically add to user's library
    purchase = UserPurchasedAgent(
        user_id=current_user.id,
        agent_id=forked_agent.id,
        purchase_type="free",
        is_active=True
    )
    db.add(purchase)
    await db.commit()

    return {
        "message": "Agent forked successfully",
        "agent_id": forked_agent.id,
        "slug": forked_agent.slug,
        "success": True
    }


@router.post("/agents/create")
async def create_custom_agent(
    name: str,
    description: str,
    system_prompt: str,
    mode: str = "stream",
    agent_type: str = "StreamAgent",
    model: str = "qwen-3-235b-a22b-thinking-2507",
    category: str = "custom",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
):
    """
    Create a custom agent from scratch.
    """
    # Generate slug from name
    import re
    slug_base = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    slug = f"{slug_base}-{current_user.id}-{datetime.now(timezone.utc).timestamp()}"

    # Create custom agent
    custom_agent = MarketplaceAgent(
        name=name,
        slug=slug,
        description=description,
        long_description=description,
        category=category,
        item_type="agent",
        system_prompt=system_prompt,
        mode=mode,
        agent_type=agent_type,
        tools=None,
        model=model,
        is_forkable=False,
        parent_agent_id=None,
        forked_by_user_id=current_user.id,
        config={},
        icon="🤖",
        preview_image=None,
        pricing_type="free",
        price=0,
        source_type="open",
        requires_user_keys=False,
        downloads=0,
        rating=5.0,
        reviews_count=0,
        features=["Custom agent"],
        required_models=[model],
        tags=["custom"],
        is_featured=False,
        is_active=True,
        is_published=False
    )

    db.add(custom_agent)
    await db.commit()
    await db.refresh(custom_agent)

    # Automatically add to user's library
    purchase = UserPurchasedAgent(
        user_id=current_user.id,
        agent_id=custom_agent.id,
        purchase_type="free",
        is_active=True
    )
    db.add(purchase)
    await db.commit()

    return {
        "message": "Custom agent created successfully",
        "agent_id": custom_agent.id,
        "slug": custom_agent.slug,
        "success": True
    }


@router.patch("/agents/{agent_id}")
async def update_custom_agent(
    agent_id: str,
    update_data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
):
    """
    Update a custom or forked agent.
    For open source agents not owned by user, creates a fork with the changes.
    """
    # Get the agent
    result = await db.execute(
        select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id)
    )
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Check if user owns this agent (created/forked by them)
    is_owner = agent.forked_by_user_id == current_user.id

    # Check if agent is open source and user has it in library
    if not is_owner:
        # Check if user has purchased this agent
        purchase_result = await db.execute(
            select(UserPurchasedAgent).where(
                UserPurchasedAgent.user_id == current_user.id,
                UserPurchasedAgent.agent_id == agent_id,
                UserPurchasedAgent.is_active == True
            )
        )
        has_agent = purchase_result.scalar_one_or_none() is not None

        if not has_agent:
            raise HTTPException(status_code=403, detail="You don't have this agent in your library")

        # If agent is open source but not owned by user, create a fork instead
        if agent.source_type == 'open':
            # Create a forked copy with the updates
            forked_slug = f"{agent.slug}-fork-{current_user.id}-{datetime.now(timezone.utc).timestamp()}"

            forked_agent = MarketplaceAgent(
                name=update_data.get('name', agent.name),
                slug=forked_slug,
                description=update_data.get('description', agent.description),
                long_description=agent.long_description,
                category=agent.category,
                item_type=agent.item_type,
                system_prompt=update_data.get('system_prompt', agent.system_prompt),
                mode=agent.mode,
                agent_type=agent.agent_type,
                tools=update_data.get('tools', agent.tools),
                tool_configs=update_data.get('tool_configs', agent.tool_configs),
                model=update_data.get('model', agent.model),
                is_forkable=False,
                parent_agent_id=agent.id,
                forked_by_user_id=current_user.id,
                config={},
                icon=agent.icon,
                avatar_url=update_data.get('avatar_url', agent.avatar_url),
                preview_image=agent.preview_image,
                pricing_type="free",
                price=0,
                source_type="open",
                requires_user_keys=agent.requires_user_keys,
                downloads=0,
                rating=5.0,
                reviews_count=0,
                features=agent.features,
                required_models=[update_data.get('model', agent.model)],
                tags=agent.tags,
                is_featured=False,
                is_active=True,
                is_published=False
            )

            db.add(forked_agent)
            await db.flush()  # Get the ID

            # Add to user's library
            purchase = UserPurchasedAgent(
                user_id=current_user.id,
                agent_id=forked_agent.id,
                purchase_type="free",
                is_active=True
            )
            db.add(purchase)

            # Remove original from active library
            original_purchase_result = await db.execute(
                select(UserPurchasedAgent).where(
                    UserPurchasedAgent.user_id == current_user.id,
                    UserPurchasedAgent.agent_id == agent_id
                )
            )
            original_purchase = original_purchase_result.scalar_one_or_none()
            if original_purchase:
                original_purchase.is_active = False

            await db.commit()

            return {
                "message": "Created a custom fork with your changes",
                "agent_id": forked_agent.id,
                "forked": True,
                "success": True
            }
        else:
            raise HTTPException(status_code=403, detail="You can only edit open source agents or your own custom agents")

    # User owns this agent, update it directly
    if update_data.get('name'):
        agent.name = update_data['name']
    if update_data.get('description'):
        agent.description = update_data['description']
        agent.long_description = update_data['description']
    if update_data.get('system_prompt'):
        agent.system_prompt = update_data['system_prompt']
    if update_data.get('model'):
        agent.model = update_data['model']
    if 'tools' in update_data:
        agent.tools = update_data['tools']
    if 'tool_configs' in update_data:
        agent.tool_configs = update_data['tool_configs']
    if 'avatar_url' in update_data:
        agent.avatar_url = update_data['avatar_url']
    if update_data.get('model'):
        agent.required_models = [update_data['model']]

    await db.commit()

    return {
        "message": "Agent updated successfully",
        "agent_id": agent.id,
        "success": True
    }


@router.get("/my-agents")
async def get_user_agents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
):
    """
    Get all agents in the user's library.
    """
    # Query user's purchased agents (all agents in library, regardless of enabled/disabled status)
    result = await db.execute(
        select(MarketplaceAgent, UserPurchasedAgent)
        .join(UserPurchasedAgent, UserPurchasedAgent.agent_id == MarketplaceAgent.id)
        .where(
            UserPurchasedAgent.user_id == current_user.id
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
            "agent_type": agent.agent_type,  # StreamAgent, IterativeAgent, etc.
            "model": agent.model,
            "selected_model": purchase.selected_model,  # User's model override
            "source_type": agent.source_type,
            "is_forkable": agent.is_forkable,
            "system_prompt": agent.system_prompt,  # Include for editing
            "icon": agent.icon,
            "avatar_url": agent.avatar_url,  # Custom logo/profile picture
            "pricing_type": agent.pricing_type,
            "features": agent.features,
            "tools": agent.tools,  # List of enabled tool names
            "tool_configs": agent.tool_configs,  # Custom tool descriptions/examples
            "purchase_date": purchase.purchase_date.isoformat(),
            "purchase_type": purchase.purchase_type,
            "expires_at": purchase.expires_at.isoformat() if purchase.expires_at else None,
            "is_custom": agent.forked_by_user_id == current_user.id,
            "parent_agent_id": agent.parent_agent_id,
            "is_enabled": purchase.is_active,  # Using is_active as is_enabled
            "is_published": agent.is_published,  # Whether agent is published to marketplace
            "usage_count": agent.usage_count or 0  # Number of messages sent
        })

    return {"agents": response}


@router.post("/agents/{agent_id}/toggle")
async def toggle_agent(
    agent_id: str,
    enabled: bool,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
):
    """
    Toggle an agent enabled/disabled in user's library.
    """
    # Find the purchase record
    result = await db.execute(
        select(UserPurchasedAgent).where(
            UserPurchasedAgent.user_id == current_user.id,
            UserPurchasedAgent.agent_id == agent_id
        )
    )
    purchase = result.scalar_one_or_none()

    if not purchase:
        raise HTTPException(status_code=404, detail="Agent not in your library")

    # Update enabled status
    purchase.is_active = enabled
    await db.commit()

    return {
        "message": f"Agent {'enabled' if enabled else 'disabled'} successfully",
        "agent_id": agent_id,
        "enabled": enabled,
        "success": True
    }


@router.delete("/agents/{agent_id}/library")
async def remove_agent_from_library(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
):
    """
    Remove an agent from user's library (delete purchase record).
    """
    # Find the purchase record
    result = await db.execute(
        select(UserPurchasedAgent).where(
            UserPurchasedAgent.user_id == current_user.id,
            UserPurchasedAgent.agent_id == agent_id
        )
    )
    purchase = result.scalar_one_or_none()

    if not purchase:
        raise HTTPException(status_code=404, detail="Agent not in your library")

    # Check if agent is assigned to any projects
    project_assignments_result = await db.execute(
        select(ProjectAgent).where(ProjectAgent.agent_id == agent_id)
    )
    project_assignments = project_assignments_result.scalars().all()

    if project_assignments:
        # Remove from all projects first
        for assignment in project_assignments:
            await db.delete(assignment)

    # Delete the purchase record
    await db.delete(purchase)
    await db.commit()

    return {
        "message": "Agent removed from library successfully",
        "agent_id": agent_id,
        "success": True
    }


@router.post("/agents/{agent_id}/select-model")
async def select_agent_model(
    agent_id: str,
    model: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
):
    """
    Set the user's selected model for an agent in their library.
    Only works for open source agents.
    """
    # Get the agent
    agent_result = await db.execute(
        select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id)
    )
    agent = agent_result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Check if agent is open source or custom
    if agent.source_type != 'open' and agent.forked_by_user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Model selection is only available for open source agents"
        )

    # Find the purchase record
    result = await db.execute(
        select(UserPurchasedAgent).where(
            UserPurchasedAgent.user_id == current_user.id,
            UserPurchasedAgent.agent_id == agent_id
        )
    )
    purchase = result.scalar_one_or_none()

    if not purchase:
        raise HTTPException(status_code=404, detail="Agent not in your library")

    # Update selected model
    purchase.selected_model = model
    await db.commit()

    return {
        "message": "Model selection updated successfully",
        "agent_id": agent_id,
        "selected_model": model,
        "success": True
    }


@router.post("/agents/{agent_id}/publish")
async def publish_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
):
    """
    Publish a user's custom/forked agent to the community marketplace.
    """
    # Get the agent
    result = await db.execute(
        select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id)
    )
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Verify ownership
    if agent.forked_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only publish your own custom agents")

    # Check if user has this agent in library
    purchase_result = await db.execute(
        select(UserPurchasedAgent).where(
            UserPurchasedAgent.user_id == current_user.id,
            UserPurchasedAgent.agent_id == agent_id,
            UserPurchasedAgent.is_active == True
        )
    )
    if not purchase_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Agent not in your library")

    # Publish the agent
    agent.is_published = True
    agent.source_type = "open"  # Published community agents are open source
    agent.is_forkable = True  # Allow others to fork it

    await db.commit()

    return {
        "message": "Agent published successfully to the community marketplace!",
        "agent_id": agent_id,
        "success": True
    }


@router.post("/agents/{agent_id}/unpublish")
async def unpublish_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
):
    """
    Unpublish a user's agent from the community marketplace.
    """
    # Get the agent
    result = await db.execute(
        select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id)
    )
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Verify ownership
    if agent.forked_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only unpublish your own agents")

    # Unpublish the agent
    agent.is_published = False

    await db.commit()

    return {
        "message": "Agent unpublished successfully",
        "agent_id": agent_id,
        "success": True
    }


# ============================================================================
# Project Agent Management
# ============================================================================

@router.get("/projects/{project_id}/available-agents")
async def get_available_agents_for_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
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

    # Get user's purchased agents (all agents in library, regardless of enabled/disabled status)
    purchased_result = await db.execute(
        select(MarketplaceAgent, UserPurchasedAgent)
        .join(UserPurchasedAgent, UserPurchasedAgent.agent_id == MarketplaceAgent.id)
        .where(
            UserPurchasedAgent.user_id == current_user.id
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
                "agent_type": agent.agent_type,  # StreamAgent, IterativeAgent, etc.
                "icon": agent.icon,
                "features": agent.features
            })

    return {"available_agents": available_agents}


@router.post("/projects/{project_id}/agents/{agent_id}")
async def add_agent_to_project(
    project_id: str,
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
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
    project_id: str,
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
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
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
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
            "agent_type": agent.agent_type,  # StreamAgent, IterativeAgent, etc.
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
    agent_id: str,
    rating: int = Query(ge=1, le=5),
    comment: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
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


# ============================================================================
# Marketplace Bases Endpoints
# ============================================================================

@router.get("/bases")
async def get_marketplace_bases(
    category: Optional[str] = None,
    pricing_type: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = Query(default="featured", regex="^(featured|popular|newest|price_asc|price_desc)$"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=12, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
):
    """Browse marketplace bases with filtering and sorting."""
    query = select(MarketplaceBase).where(MarketplaceBase.is_active == True)

    # Apply filters
    if category:
        query = query.where(MarketplaceBase.category == category)
    if pricing_type:
        query = query.where(MarketplaceBase.pricing_type == pricing_type)
    if search:
        search_filter = f"%{search}%"
        query = query.where(
            func.lower(MarketplaceBase.name).like(func.lower(search_filter)) |
            func.lower(MarketplaceBase.description).like(func.lower(search_filter))
        )

    # Apply sorting
    if sort == "featured":
        query = query.order_by(MarketplaceBase.is_featured.desc(), MarketplaceBase.downloads.desc())
    elif sort == "popular":
        query = query.order_by(MarketplaceBase.downloads.desc())
    elif sort == "newest":
        query = query.order_by(MarketplaceBase.created_at.desc())
    elif sort == "price_asc":
        query = query.order_by(MarketplaceBase.price.asc())
    elif sort == "price_desc":
        query = query.order_by(MarketplaceBase.price.desc())

    # Pagination
    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    bases = result.scalars().all()

    # Get user's purchased bases
    purchased_result = await db.execute(
        select(UserPurchasedBase.base_id).where(
            UserPurchasedBase.user_id == current_user.id,
            UserPurchasedBase.is_active == True
        )
    )
    purchased_base_ids = [row[0] for row in purchased_result.fetchall()]

    # Format response
    response = []
    for base in bases:
        response.append({
            "id": base.id,
            "name": base.name,
            "slug": base.slug,
            "description": base.description,
            "long_description": base.long_description,
            "git_repo_url": base.git_repo_url,
            "default_branch": base.default_branch,
            "category": base.category,
            "icon": base.icon,
            "preview_image": base.preview_image,
            "pricing_type": base.pricing_type,
            "price": base.price / 100.0 if base.price else 0,
            "downloads": base.downloads,
            "rating": base.rating,
            "reviews_count": base.reviews_count,
            "features": base.features,
            "tech_stack": base.tech_stack,
            "tags": base.tags,
            "is_featured": base.is_featured,
            "is_active": base.is_active,
            "is_purchased": base.id in purchased_base_ids,
            "source_type": "open",  # All bases are open source
            "is_forkable": False,  # Bases can't be forked
            "usage_count": base.downloads
        })

    return {
        "bases": response,
        "page": page,
        "limit": limit,
        "has_more": len(bases) == limit
    }


@router.get("/bases/{slug}")
async def get_base_details(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
):
    """Get detailed information about a specific base."""
    result = await db.execute(
        select(MarketplaceBase).where(MarketplaceBase.slug == slug)
    )
    base = result.scalar_one_or_none()

    if not base:
        raise HTTPException(status_code=404, detail="Base not found")

    # Check if user has purchased this base
    purchased_result = await db.execute(
        select(UserPurchasedBase).where(
            UserPurchasedBase.user_id == current_user.id,
            UserPurchasedBase.base_id == base.id,
            UserPurchasedBase.is_active == True
        )
    )
    is_purchased = purchased_result.scalar_one_or_none() is not None

    # Get recent reviews
    reviews_result = await db.execute(
        select(BaseReview).where(BaseReview.base_id == base.id)
        .order_by(BaseReview.created_at.desc())
        .limit(5)
    )
    reviews = reviews_result.scalars().all()

    return {
        "id": base.id,
        "name": base.name,
        "slug": base.slug,
        "description": base.description,
        "long_description": base.long_description,
        "git_repo_url": base.git_repo_url,
        "default_branch": base.default_branch,
        "category": base.category,
        "icon": base.icon,
        "preview_image": base.preview_image,
        "pricing_type": base.pricing_type,
        "price": base.price / 100.0 if base.price else 0,
        "downloads": base.downloads,
        "rating": base.rating,
        "reviews_count": base.reviews_count,
        "features": base.features,
        "tech_stack": base.tech_stack,
        "tags": base.tags,
        "is_featured": base.is_featured,
        "is_active": base.is_active,
        "is_purchased": is_purchased,
        "source_type": "open",
        "is_forkable": False,
        "usage_count": base.downloads,
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


@router.post("/bases/{base_id}/purchase")
async def purchase_base(
    base_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
):
    """Purchase or add a free base to user's library."""
    # Get base
    result = await db.execute(
        select(MarketplaceBase).where(MarketplaceBase.id == base_id)
    )
    base = result.scalar_one_or_none()

    if not base or not base.is_active:
        raise HTTPException(status_code=404, detail="Base not found")

    # Check if already purchased
    existing_result = await db.execute(
        select(UserPurchasedBase).where(
            UserPurchasedBase.user_id == current_user.id,
            UserPurchasedBase.base_id == base_id
        )
    )
    existing_purchase = existing_result.scalar_one_or_none()

    if existing_purchase and existing_purchase.is_active:
        return {"message": "Base already in your library", "base_id": base_id}

    # Handle free bases
    if base.pricing_type == "free":
        if existing_purchase:
            existing_purchase.is_active = True
            existing_purchase.purchase_date = datetime.now(timezone.utc)
        else:
            purchase = UserPurchasedBase(
                user_id=current_user.id,
                base_id=base_id,
                purchase_type="free",
                is_active=True
            )
            db.add(purchase)

        base.downloads += 1
        await db.commit()

        return {
            "message": "Free base added to your library",
            "base_id": base_id,
            "success": True
        }

    # For paid bases (Stripe integration - similar to agents)
    raise HTTPException(status_code=501, detail="Paid bases not yet implemented")


@router.get("/my-bases")
async def get_user_bases(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
):
    """Get all bases in the user's library."""
    result = await db.execute(
        select(MarketplaceBase, UserPurchasedBase)
        .join(UserPurchasedBase, UserPurchasedBase.base_id == MarketplaceBase.id)
        .where(
            UserPurchasedBase.user_id == current_user.id,
            UserPurchasedBase.is_active == True
        )
        .order_by(UserPurchasedBase.purchase_date.desc())
    )

    bases_data = result.fetchall()

    response = []
    for base, purchase in bases_data:
        response.append({
            "id": base.id,
            "name": base.name,
            "slug": base.slug,
            "description": base.description,
            "git_repo_url": base.git_repo_url,
            "default_branch": base.default_branch,
            "category": base.category,
            "icon": base.icon,
            "pricing_type": base.pricing_type,
            "features": base.features,
            "tech_stack": base.tech_stack,
            "purchase_date": purchase.purchase_date.isoformat(),
            "purchase_type": purchase.purchase_type
        })

    return {"bases": response}


@router.get("/my-items")
async def get_user_marketplace_items(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
):
    """
    Get all marketplace items in the user's library.
    Returns bases, services (container, external, hybrid), and workflows in a unified format.
    """
    from ..services.service_definitions import get_all_services, service_to_dict

    # Fetch user's purchased bases
    result = await db.execute(
        select(MarketplaceBase, UserPurchasedBase)
        .join(UserPurchasedBase, UserPurchasedBase.base_id == MarketplaceBase.id)
        .where(
            UserPurchasedBase.user_id == current_user.id,
            UserPurchasedBase.is_active == True
        )
        .order_by(UserPurchasedBase.purchase_date.desc())
    )

    bases_data = result.fetchall()

    # Build unified response
    items = []

    # Add bases
    for base, purchase in bases_data:
        items.append({
            "id": str(base.id),
            "name": base.name,
            "slug": base.slug,
            "description": base.description,
            "icon": base.icon,
            "category": base.category,
            "tech_stack": base.tech_stack or [],
            "features": base.features or [],
            "type": "base",
            # Base-specific fields
            "git_repo_url": base.git_repo_url,
            "default_branch": base.default_branch,
            "pricing_type": base.pricing_type,
            "purchase_date": purchase.purchase_date.isoformat(),
            "purchase_type": purchase.purchase_type
        })

    # Add all services (available to all users by default)
    services = get_all_services()
    for service in services:
        service_data = service_to_dict(service)
        items.append({
            "id": f"service-{service.slug}",  # Unique ID for services
            "name": service.name,
            "slug": service.slug,
            "description": service.description,
            "icon": service.icon,
            "category": service.category,
            "tech_stack": [service.docker_image] if service.docker_image else [],
            "features": list(service.outputs.keys()) if service.outputs else [],
            "type": "service",
            # Service type (container, external, hybrid)
            "service_type": service_data["service_type"],
            # Container-specific fields
            "docker_image": service.docker_image,
            "default_port": service.default_port,
            "internal_port": service.internal_port,
            "environment_vars": service.environment_vars,
            "volumes": service.volumes,
            # External service fields
            "credential_fields": service_data["credential_fields"],
            "auth_type": service_data["auth_type"],
            "docs_url": service.docs_url,
            # Connection configuration
            "connection_template": service.connection_template,
            "outputs": service.outputs
        })

    # Add workflows (available to all users)
    from ..models import WorkflowTemplate
    workflow_result = await db.execute(
        select(WorkflowTemplate).where(WorkflowTemplate.is_active == True)
    )
    workflows = workflow_result.scalars().all()

    for workflow in workflows:
        items.append({
            "id": str(workflow.id),
            "name": workflow.name,
            "slug": workflow.slug,
            "description": workflow.description,
            "icon": workflow.icon,
            "category": workflow.category,
            "tech_stack": workflow.tags or [],
            "features": workflow.required_credentials or [],
            "type": "workflow",
            # Workflow-specific fields
            "template_definition": workflow.template_definition,
            "required_credentials": workflow.required_credentials,
            "preview_image": workflow.preview_image,
            "pricing_type": workflow.pricing_type,
            "downloads": workflow.downloads,
            "is_featured": workflow.is_featured
        })

    return {"items": items}


# ============================================================================
# Workflow Template Endpoints
# ============================================================================

@router.get("/workflows")
async def list_workflows(
    category: Optional[str] = None,
    is_featured: Optional[bool] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """List all workflow templates with optional filtering."""
    from ..models import WorkflowTemplate

    query = select(WorkflowTemplate).where(WorkflowTemplate.is_active == True)

    if category:
        query = query.where(WorkflowTemplate.category == category)
    if is_featured is not None:
        query = query.where(WorkflowTemplate.is_featured == is_featured)
    if search:
        query = query.where(
            WorkflowTemplate.name.ilike(f"%{search}%") |
            WorkflowTemplate.description.ilike(f"%{search}%")
        )

    query = query.order_by(WorkflowTemplate.downloads.desc())

    result = await db.execute(query)
    workflows = result.scalars().all()

    return {
        "workflows": [
            {
                "id": str(w.id),
                "name": w.name,
                "slug": w.slug,
                "description": w.description,
                "icon": w.icon,
                "category": w.category,
                "tags": w.tags,
                "preview_image": w.preview_image,
                "required_credentials": w.required_credentials,
                "pricing_type": w.pricing_type,
                "price": w.price,
                "downloads": w.downloads,
                "rating": w.rating,
                "is_featured": w.is_featured
            }
            for w in workflows
        ]
    }


@router.get("/workflows/{slug}")
async def get_workflow(
    slug: str,
    db: AsyncSession = Depends(get_db)
):
    """Get a workflow template by slug, including full template definition."""
    from ..models import WorkflowTemplate

    result = await db.execute(
        select(WorkflowTemplate).where(
            WorkflowTemplate.slug == slug,
            WorkflowTemplate.is_active == True
        )
    )
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return {
        "id": str(workflow.id),
        "name": workflow.name,
        "slug": workflow.slug,
        "description": workflow.description,
        "long_description": workflow.long_description,
        "icon": workflow.icon,
        "category": workflow.category,
        "tags": workflow.tags,
        "preview_image": workflow.preview_image,
        "template_definition": workflow.template_definition,
        "required_credentials": workflow.required_credentials,
        "pricing_type": workflow.pricing_type,
        "price": workflow.price,
        "downloads": workflow.downloads,
        "rating": workflow.rating,
        "reviews_count": workflow.reviews_count,
        "is_featured": workflow.is_featured
    }


@router.post("/workflows/{slug}/increment-downloads")
async def increment_workflow_downloads(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
):
    """Increment the download count for a workflow template."""
    from ..models import WorkflowTemplate

    result = await db.execute(
        select(WorkflowTemplate).where(WorkflowTemplate.slug == slug)
    )
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow.downloads += 1
    await db.commit()

    return {"success": True, "downloads": workflow.downloads}