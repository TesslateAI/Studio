"""
Marketplace API endpoints for browsing, purchasing, and managing agents.
"""

from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
import logging

from ..database import get_db
from ..auth import get_current_active_user
from ..models import (
    User, MarketplaceAgent, UserPurchasedAgent,
    ProjectAgent, AgentReview, Project,
    MarketplaceBase, UserPurchasedBase, BaseReview
)
from ..schemas import MarketplaceAgentResponse, AgentPurchaseRequest

logger = logging.getLogger(__name__)
router = APIRouter()

from ..config import get_settings
settings = get_settings()


# ============================================================================
# Models Configuration
# ============================================================================

@router.get("/models")
async def get_available_models(
    current_user: User = Depends(get_current_active_user),
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
        "gpt-5": {"input": 30.0, "output": 60.0},
        "gpt-5-turbo": {"input": 10.0, "output": 30.0},
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
    provider: str = Body(..., description="Provider name (openrouter, ollama, lmstudio, llamacpp, custom)"),
    pricing_input: Optional[float] = Body(None),
    pricing_output: Optional[float] = Body(None),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Add a custom model from any provider to the user's account.
    Supports: openrouter, ollama, lmstudio, llamacpp, custom endpoints.
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
        provider=provider,
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
    current_user: User = Depends(get_current_active_user),
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


@router.post("/models/fetch")
async def fetch_provider_models(
    provider: str = Body(..., description="Provider name (openrouter, ollama, lmstudio, llamacpp, custom)"),
    base_url: Optional[str] = Body(None, description="Override base URL for this request"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Fetch available models from a provider's API endpoint.
    Supports OpenRouter, Ollama, LM Studio, llama.cpp, and custom OpenAI-compatible endpoints.
    """
    import aiohttp
    from ..models import UserAPIKey
    from ..routers.secrets import decode_key

    # Get user's API key/config for this provider
    key_query = select(UserAPIKey).where(
        UserAPIKey.user_id == current_user.id,
        UserAPIKey.provider == provider,
        UserAPIKey.is_active == True
    )
    result = await db.execute(key_query)
    api_key_record = result.scalar_one_or_none()

    if not api_key_record:
        raise HTTPException(
            status_code=400,
            detail=f"No configuration found for {provider}. Please add API configuration first."
        )

    # Determine base URL and API key
    if base_url:
        # Use override URL if provided
        fetch_base_url = base_url
    elif provider == "custom":
        fetch_base_url = api_key_record.provider_metadata.get("base_url")
        if not fetch_base_url:
            raise HTTPException(
                status_code=400,
                detail="No base URL configured for custom endpoint"
            )
    elif provider == "openrouter":
        fetch_base_url = api_key_record.provider_metadata.get(
            "base_url",
            "https://openrouter.ai/api/v1"
        )
    elif provider == "ollama":
        fetch_base_url = api_key_record.provider_metadata.get(
            "base_url",
            "http://localhost:11434"
        )
    elif provider == "lmstudio":
        fetch_base_url = api_key_record.provider_metadata.get(
            "base_url",
            "http://localhost:1234"
        )
    elif provider == "llamacpp":
        fetch_base_url = api_key_record.provider_metadata.get(
            "base_url",
            "http://localhost:8080"
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    # Get API key if provider requires it
    api_key = None
    if provider in ["openrouter", "custom"]:
        try:
            api_key = decode_key(api_key_record.encrypted_value)
        except Exception:
            api_key = None

    # Determine endpoint path
    if provider == "ollama":
        endpoint = f"{fetch_base_url}/api/tags"
    else:
        # OpenRouter, LM Studio, llama.cpp, custom all use OpenAI-compatible /v1/models
        endpoint = f"{fetch_base_url}/v1/models" if not fetch_base_url.endswith("/v1/models") else fetch_base_url

    # Fetch models from provider API
    async with aiohttp.ClientSession() as session:
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            async with session.get(endpoint, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to fetch models from {provider}: {error_text[:200]}"
                    )

                data = await resp.json()

                # Parse response based on provider format
                if provider == "ollama":
                    # Ollama format: { models: [{ name, size, modified_at }] }
                    models = [
                        {
                            "id": m["name"],
                            "name": m["name"],
                            "provider": provider,
                            "size": m.get("size", 0),
                            "modified_at": m.get("modified_at")
                        }
                        for m in data.get("models", [])
                    ]
                elif provider == "openrouter":
                    # OpenRouter format: { data: [{ id, name, pricing }] }
                    models = [
                        {
                            "id": m["id"],
                            "name": m.get("name", m["id"]),
                            "provider": provider,
                            "pricing": m.get("pricing", {})
                        }
                        for m in data.get("data", [])
                    ]
                else:
                    # OpenAI-compatible format: { data: [{ id, object: "model" }] }
                    # Used by lmstudio, llamacpp, custom
                    models = [
                        {
                            "id": m["id"],
                            "name": m.get("name", m["id"]),
                            "provider": provider
                        }
                        for m in data.get("data", [])
                    ]

                return {
                    "models": models,
                    "count": len(models),
                    "provider": provider,
                    "endpoint": endpoint
                }

        except aiohttp.ClientError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Network error connecting to {provider}: {str(e)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error fetching models from {provider}: {str(e)}"
            )


@router.post("/models/import-batch")
async def import_batch_models(
    provider: str = Body(..., description="Provider name"),
    models: list = Body(..., description="List of models to import with {model_id, model_name}"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Import multiple models at once from a provider.
    Used after fetching models to batch import selected ones.
    """
    from ..models import UserCustomModel

    imported_count = 0
    skipped_count = 0
    errors = []

    for model_data in models:
        model_id = model_data.get("model_id") or model_data.get("id")
        model_name = model_data.get("model_name") or model_data.get("name") or model_id

        # Add provider prefix if not present
        if not model_id.startswith(f"{provider}/"):
            model_id = f"{provider}/{model_id}"

        try:
            # Check if model already exists
            existing_query = select(UserCustomModel).where(
                UserCustomModel.user_id == current_user.id,
                UserCustomModel.model_id == model_id,
                UserCustomModel.is_active == True
            )
            result = await db.execute(existing_query)
            existing = result.scalar_one_or_none()

            if existing:
                skipped_count += 1
                continue

            # Extract pricing if provided (for OpenRouter)
            pricing_input = model_data.get("pricing", {}).get("prompt") if "pricing" in model_data else None
            pricing_output = model_data.get("pricing", {}).get("completion") if "pricing" in model_data else None

            # Create new custom model
            custom_model = UserCustomModel(
                user_id=current_user.id,
                model_id=model_id,
                model_name=model_name,
                provider=provider,
                pricing_input=pricing_input,
                pricing_output=pricing_output
            )

            db.add(custom_model)
            imported_count += 1

        except Exception as e:
            errors.append({"model_id": model_id, "error": str(e)})
            skipped_count += 1

    # Commit all imports at once
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to import models: {str(e)}"
        )

    return {
        "message": f"Imported {imported_count} models from {provider}",
        "imported": imported_count,
        "skipped": skipped_count,
        "total": len(models),
        "errors": errors if errors else None,
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
    current_user: User = Depends(get_current_active_user)
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
        "agent_type": agent.agent_type,  # StreamAgent, IterativeAgent, etc.
        "system_prompt": agent.system_prompt,  # Include system prompt for forking
        "model": agent.model,
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
    settings = get_settings()

    # Create checkout session with config-based URLs
    protocol = "https" if settings.deployment_mode == "kubernetes" else "http"
    base_url = f"{protocol}://{settings.app_domain}"
    success_url = f"{base_url}/marketplace/success?agent={agent.slug}"
    cancel_url = f"{base_url}/marketplace/agent/{agent.slug}"

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


@router.post("/agents/{agent_id}/fork")
async def fork_agent(
    agent_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
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
    model: str = "cerebras/qwen-3-coder-480b",
    category: str = "custom",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
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
    current_user: User = Depends(get_current_active_user)
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
                tools=agent.tools,
                model=update_data.get('model', agent.model),
                is_forkable=False,
                parent_agent_id=agent.id,
                forked_by_user_id=current_user.id,
                config={},
                icon=agent.icon,
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
    current_user: User = Depends(get_current_active_user)
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
            "pricing_type": agent.pricing_type,
            "features": agent.features,
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
    current_user: User = Depends(get_current_active_user)
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
    current_user: User = Depends(get_current_active_user)
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
    current_user: User = Depends(get_current_active_user)
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
    current_user: User = Depends(get_current_active_user)
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
    current_user: User = Depends(get_current_active_user)
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
    project_id: str,
    agent_id: str,
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
    project_id: str,
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
    current_user: User = Depends(get_current_active_user)
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
    current_user: User = Depends(get_current_active_user)
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
    current_user: User = Depends(get_current_active_user)
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
    current_user: User = Depends(get_current_active_user)
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