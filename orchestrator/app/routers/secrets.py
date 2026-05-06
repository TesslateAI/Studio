"""
API Keys and Secrets Management endpoints.
Handles storage and management of user API keys for various providers.
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models import User, UserAPIKey
from ..services.deployment_encryption import (
    DeploymentEncryptionError,
    get_deployment_encryption_service,
)
from ..users import current_active_user

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()


async def _require_byok(user: User, db: AsyncSession) -> None:
    """Raise 403 if the user's active team tier does not support BYOK.

    Billing is team-scoped — Stripe updates team.subscription_tier, not
    user.subscription_tier. Checking the team tier here keeps this consistent
    with GET /subscription, which is the source of truth for the frontend gate.
    """
    from ..models_team import Team

    tier = "free"
    if user.default_team_id:
        result = await db.execute(select(Team).where(Team.id == user.default_team_id))
        team = result.scalar_one_or_none()
        if team:
            tier = team.subscription_tier or "free"

    if tier not in settings.byok_tiers_list:
        raise HTTPException(
            status_code=403,
            detail="BYOK (Bring Your Own Key) requires a paid plan. Please upgrade to Basic, Pro, or Ultra.",
        )


def encode_key(key: str) -> str:
    """Encrypt API key using Fernet symmetric encryption for secure storage."""
    if not key:
        return ""
    try:
        service = get_deployment_encryption_service()
        return service.encrypt(key.strip())
    except DeploymentEncryptionError as e:
        logger.error(f"Failed to encrypt API key: {e}")
        raise


def decode_key(encoded: str) -> str:
    """Decrypt API key using Fernet symmetric encryption."""
    if not encoded:
        return ""
    try:
        service = get_deployment_encryption_service()
        return service.decrypt(encoded)
    except DeploymentEncryptionError as e:
        logger.error(f"Failed to decrypt API key: {e}")
        raise


@router.get("/api-keys")
async def list_api_keys(
    provider: str | None = None,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all API keys for the current user.
    """
    team_id = current_user.default_team_id
    ownership_filter = (
        UserAPIKey.team_id == team_id if team_id else UserAPIKey.user_id == current_user.id
    )
    query = select(UserAPIKey).where(ownership_filter, UserAPIKey.is_active.is_(True))

    if provider:
        query = query.where(UserAPIKey.provider == provider)

    query = query.order_by(UserAPIKey.created_at.desc())

    result = await db.execute(query)
    api_keys = result.scalars().all()

    return {
        "api_keys": [
            {
                "id": key.id,
                "provider": key.provider,
                "auth_type": key.auth_type,
                "key_name": key.key_name,
                "key_preview": decode_key(key.encrypted_value)[:8] + "..."
                if key.encrypted_value
                else None,
                "base_url": key.base_url,
                "provider_metadata": key.provider_metadata,
                "expires_at": key.expires_at.isoformat() if key.expires_at else None,
                "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
                "created_at": key.created_at.isoformat(),
            }
            for key in api_keys
        ]
    }


@router.post("/api-keys")
async def add_api_key(
    provider: str = Body(
        ..., description="Provider name (openrouter, anthropic, openai, google, etc.)"
    ),
    api_key: str = Body(..., description="The API key value"),
    auth_type: str = Body(default="api_key", description="Authentication type"),
    key_name: str | None = Body(None, description="Optional name for this key"),
    base_url: str | None = Body(None, description="Optional custom base URL override"),
    provider_metadata: dict | None = Body(default={}, description="Provider-specific metadata"),
    expires_at: str | None = Body(None, description="Optional expiration date"),
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Add a new API key for a provider.
    """
    await _require_byok(current_user, db)

    # Default key_name to provider display name if not provided
    if not key_name:
        from ..services.model_adapters import BUILTIN_PROVIDERS

        provider_config = BUILTIN_PROVIDERS.get(provider)
        key_name = provider_config["name"] if provider_config else provider.title()

    # Check if key with same provider and name already exists
    team_id = current_user.default_team_id
    ownership_filter = (
        UserAPIKey.team_id == team_id if team_id else UserAPIKey.user_id == current_user.id
    )
    existing_query = select(UserAPIKey).where(
        ownership_filter,
        UserAPIKey.provider == provider,
        UserAPIKey.key_name == key_name,
    )
    result = await db.execute(existing_query)
    existing_key = result.scalar_one_or_none()

    if existing_key:
        if existing_key.is_active:
            raise HTTPException(
                status_code=400,
                detail=f"API key for {provider}"
                + (f" with name '{key_name}'" if key_name else "")
                + " already exists",
            )
        else:
            # Reactivate existing key
            existing_key.encrypted_value = encode_key(api_key)
            existing_key.base_url = base_url or None
            existing_key.is_active = True
            existing_key.provider_metadata = provider_metadata
            existing_key.expires_at = datetime.fromisoformat(expires_at) if expires_at else None
            existing_key.updated_at = datetime.now(UTC)
            await db.commit()
            await db.refresh(existing_key)
            return {"message": "API key reactivated", "key_id": existing_key.id, "success": True}

    # Create new API key
    new_key = UserAPIKey(
        user_id=current_user.id,
        team_id=current_user.default_team_id,
        provider=provider,
        auth_type=auth_type,
        key_name=key_name,
        base_url=base_url or None,
        encrypted_value=encode_key(api_key),
        provider_metadata=provider_metadata or {},
        expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
        is_active=True,
    )

    db.add(new_key)
    await db.commit()
    await db.refresh(new_key)

    return {
        "message": "API key added successfully",
        "key_id": new_key.id,
        "provider": provider,
        "success": True,
    }


@router.put("/api-keys/{key_id}")
async def update_api_key(
    key_id: str,
    api_key: str | None = Body(None, description="New API key value"),
    key_name: str | None = Body(None, description="New name for this key"),
    base_url: str | None = Body(
        None, description="Custom base URL override (empty string clears it)"
    ),
    provider_metadata: dict | None = Body(None, description="Updated metadata"),
    expires_at: str | None = Body(None, description="Updated expiration date"),
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update an existing API key.
    """
    team_id = current_user.default_team_id
    ownership_filter = (
        UserAPIKey.team_id == team_id if team_id else UserAPIKey.user_id == current_user.id
    )
    query = select(UserAPIKey).where(UserAPIKey.id == key_id, ownership_filter)
    result = await db.execute(query)
    key_record = result.scalar_one_or_none()

    if not key_record:
        raise HTTPException(status_code=404, detail="API key not found")

    # Update fields
    if api_key:
        key_record.encrypted_value = encode_key(api_key)
    if key_name is not None:
        key_record.key_name = key_name
    if base_url is not None:
        key_record.base_url = base_url or None  # Empty string clears it
    if provider_metadata is not None:
        key_record.provider_metadata = provider_metadata
    if expires_at is not None:
        key_record.expires_at = datetime.fromisoformat(expires_at) if expires_at else None

    key_record.updated_at = datetime.now(UTC)

    await db.commit()

    return {"message": "API key updated successfully", "key_id": key_id, "success": True}


@router.delete("/api-keys/{key_id}")
async def delete_api_key(
    key_id: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete (deactivate) an API key.
    """
    team_id = current_user.default_team_id
    ownership_filter = (
        UserAPIKey.team_id == team_id if team_id else UserAPIKey.user_id == current_user.id
    )
    query = select(UserAPIKey).where(UserAPIKey.id == key_id, ownership_filter)
    result = await db.execute(query)
    key_record = result.scalar_one_or_none()

    if not key_record:
        raise HTTPException(status_code=404, detail="API key not found")

    # Soft delete
    key_record.is_active = False
    key_record.updated_at = datetime.now(UTC)

    await db.commit()

    return {"message": "API key deleted successfully", "success": True}


@router.get("/api-keys/{key_id}")
async def get_api_key(
    key_id: str,
    reveal: bool = False,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a specific API key. Use reveal=true to get the full key value.
    """
    team_id = current_user.default_team_id
    ownership_filter = (
        UserAPIKey.team_id == team_id if team_id else UserAPIKey.user_id == current_user.id
    )
    query = select(UserAPIKey).where(UserAPIKey.id == key_id, ownership_filter)
    result = await db.execute(query)
    key_record = result.scalar_one_or_none()

    if not key_record:
        raise HTTPException(status_code=404, detail="API key not found")

    decoded_key = decode_key(key_record.encrypted_value) if key_record.encrypted_value else None

    return {
        "id": key_record.id,
        "provider": key_record.provider,
        "auth_type": key_record.auth_type,
        "key_name": key_record.key_name,
        "base_url": key_record.base_url,
        "key_value": decoded_key if reveal else None,
        "key_preview": decoded_key[:8] + "..." if decoded_key and not reveal else None,
        "provider_metadata": key_record.provider_metadata,
        "expires_at": key_record.expires_at.isoformat() if key_record.expires_at else None,
        "last_used_at": key_record.last_used_at.isoformat() if key_record.last_used_at else None,
        "created_at": key_record.created_at.isoformat(),
        "is_active": key_record.is_active,
    }


@router.get("/providers")
async def list_supported_providers(current_user: User = Depends(current_active_user)):
    """
    List all supported LLM providers and their configuration.
    Returns built-in providers from the centralized registry.
    """
    from ..services.model_adapters import BUILTIN_PROVIDERS

    # Convert BUILTIN_PROVIDERS to list format with consistent structure
    providers = [
        {
            "id": slug,
            "name": config["name"],
            "description": config.get("description", ""),
            "auth_type": "api_key",
            "website": config.get("website", ""),
            "requires_key": config.get("requires_key", True),
            "supports_oauth": False,
            "base_url": config["base_url"],
            "api_type": config.get("api_type", "openai"),
        }
        for slug, config in BUILTIN_PROVIDERS.items()
    ]

    # Add non-LLM providers (Google, GitHub for integrations)
    integration_providers = [
        {
            "id": "google",
            "name": "Google",
            "description": "Google OAuth for integrations",
            "auth_type": "oauth",
            "website": "https://google.com",
            "requires_key": False,
            "supports_oauth": True,
        },
        {
            "id": "github",
            "name": "GitHub",
            "description": "GitHub Copilot and Models",
            "auth_type": "personal_access_token",
            "website": "https://github.com",
            "requires_key": True,
            "supports_oauth": True,
        },
    ]

    return {"providers": providers + integration_providers}


# =============================================================================
# Custom Provider Endpoints
# =============================================================================


@router.get("/providers/custom")
async def list_custom_providers(
    current_user: User = Depends(current_active_user), db: AsyncSession = Depends(get_db)
):
    """
    List all custom providers created by the current user.
    """
    from ..models import UserProvider

    team_id = current_user.default_team_id
    ownership_filter = (
        UserProvider.team_id == team_id if team_id else UserProvider.user_id == current_user.id
    )
    query = (
        select(UserProvider)
        .where(ownership_filter, UserProvider.is_active.is_(True))
        .order_by(UserProvider.created_at.desc())
    )

    result = await db.execute(query)
    providers = result.scalars().all()

    return {
        "providers": [
            {
                "id": str(p.id),
                "name": p.name,
                "slug": p.slug,
                "base_url": p.base_url,
                "api_type": p.api_type,
                "default_headers": p.default_headers,
                "available_models": p.available_models or [],
                "created_at": p.created_at.isoformat(),
            }
            for p in providers
        ]
    }


@router.post("/providers/custom")
async def create_custom_provider(
    name: str = Body(..., description="Display name for the provider"),
    slug: str = Body(..., description="URL-safe identifier (e.g., 'my-ollama')"),
    base_url: str = Body(..., description="API endpoint URL"),
    api_type: str = Body(
        default="openai", description="API compatibility: 'openai' or 'anthropic'"
    ),
    default_headers: dict | None = Body(default={}, description="Optional extra headers"),
    available_models: list[str] | None = Body(
        default=None, description="List of model IDs available on this provider"
    ),
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a custom LLM provider.

    Custom providers allow users to connect their own OpenAI-compatible or
    Anthropic-compatible API endpoints (e.g., local Ollama, vLLM, etc.)
    """
    await _require_byok(current_user, db)

    import re

    from ..models import UserProvider
    from ..services.model_adapters import BUILTIN_PROVIDERS

    # Validate slug format (alphanumeric, hyphens, underscores only)
    if not re.match(r"^[a-z0-9][a-z0-9_-]*$", slug.lower()):
        raise HTTPException(
            status_code=400,
            detail="Slug must start with a letter/number and contain only lowercase letters, numbers, hyphens, and underscores",
        )

    # Check if slug conflicts with built-in providers or reserved prefixes
    reserved_slugs = {"custom", "builtin"}
    if slug.lower() in BUILTIN_PROVIDERS or slug.lower() in reserved_slugs:
        raise HTTPException(
            status_code=400,
            detail=f"'{slug}' is a reserved provider name. Please choose a different slug.",
        )

    # Validate api_type
    if api_type not in ["openai", "anthropic"]:
        raise HTTPException(status_code=400, detail="api_type must be 'openai' or 'anthropic'")

    # Check if team/user already has a provider with this slug
    team_id = current_user.default_team_id
    ownership_filter = (
        UserProvider.team_id == team_id if team_id else UserProvider.user_id == current_user.id
    )
    existing_query = select(UserProvider).where(ownership_filter, UserProvider.slug == slug.lower())
    result = await db.execute(existing_query)
    existing_provider = result.scalar_one_or_none()

    if existing_provider:
        if existing_provider.is_active:
            raise HTTPException(
                status_code=400, detail=f"You already have a provider with slug '{slug}'"
            )
        else:
            # Reactivate existing provider
            existing_provider.name = name
            existing_provider.base_url = base_url
            existing_provider.api_type = api_type
            existing_provider.default_headers = default_headers or {}
            existing_provider.available_models = available_models
            existing_provider.is_active = True
            existing_provider.updated_at = datetime.now(UTC)
            await db.commit()
            await db.refresh(existing_provider)
            return {
                "message": "Provider reactivated",
                "provider_id": str(existing_provider.id),
                "slug": existing_provider.slug,
                "success": True,
            }

    # Create new provider
    new_provider = UserProvider(
        user_id=current_user.id,
        team_id=current_user.default_team_id,
        name=name,
        slug=slug.lower(),
        base_url=base_url,
        api_type=api_type,
        default_headers=default_headers or {},
        available_models=available_models,
        is_active=True,
    )

    db.add(new_provider)
    await db.commit()
    await db.refresh(new_provider)

    return {
        "message": "Custom provider created successfully",
        "provider_id": str(new_provider.id),
        "slug": new_provider.slug,
        "success": True,
    }


@router.put("/providers/custom/{provider_id}")
async def update_custom_provider(
    provider_id: str,
    name: str | None = Body(None, description="New display name"),
    base_url: str | None = Body(None, description="New API endpoint URL"),
    api_type: str | None = Body(None, description="New API type"),
    default_headers: dict | None = Body(None, description="New default headers"),
    available_models: list[str] | None = Body(
        None, description="Updated list of available model IDs"
    ),
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update an existing custom provider.
    """
    from ..models import UserProvider

    team_id = current_user.default_team_id
    ownership_filter = (
        UserProvider.team_id == team_id if team_id else UserProvider.user_id == current_user.id
    )
    query = select(UserProvider).where(UserProvider.id == provider_id, ownership_filter)
    result = await db.execute(query)
    provider = result.scalar_one_or_none()

    if not provider:
        raise HTTPException(status_code=404, detail="Custom provider not found")

    # Update fields
    if name is not None:
        provider.name = name
    if base_url is not None:
        provider.base_url = base_url
    if api_type is not None:
        if api_type not in ["openai", "anthropic"]:
            raise HTTPException(status_code=400, detail="api_type must be 'openai' or 'anthropic'")
        provider.api_type = api_type
    if default_headers is not None:
        provider.default_headers = default_headers
    if available_models is not None:
        provider.available_models = available_models

    provider.updated_at = datetime.now(UTC)

    await db.commit()

    return {
        "message": "Custom provider updated successfully",
        "provider_id": provider_id,
        "success": True,
    }


@router.delete("/providers/custom/{provider_id}")
async def delete_custom_provider(
    provider_id: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete (deactivate) a custom provider.
    """
    from ..models import UserProvider

    team_id = current_user.default_team_id
    ownership_filter = (
        UserProvider.team_id == team_id if team_id else UserProvider.user_id == current_user.id
    )
    query = select(UserProvider).where(UserProvider.id == provider_id, ownership_filter)
    result = await db.execute(query)
    provider = result.scalar_one_or_none()

    if not provider:
        raise HTTPException(status_code=404, detail="Custom provider not found")

    # Soft delete
    provider.is_active = False
    provider.updated_at = datetime.now(UTC)

    await db.commit()

    return {"message": "Custom provider deleted successfully", "success": True}


# =============================================================================
# Model Preferences Endpoints
# =============================================================================


@router.get("/model-preferences")
async def get_model_preferences(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get disabled model IDs for the active team.
    """
    from ..models_team import Team

    if user.default_team_id:
        result = await db.execute(select(Team).where(Team.id == user.default_team_id))
        team = result.scalar_one_or_none()
        if team:
            return {"disabled_models": team.disabled_models or []}
    return {"disabled_models": user.disabled_models or []}


@router.put("/model-preferences")
async def update_model_preferences(
    model_id: str = Body(..., embed=True),
    enabled: bool = Body(..., embed=True),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Toggle a single model on/off for the active team.
    Disabled models are hidden from the chat model selector.
    """
    from ..models_team import Team

    # Resolve target: team if available, else user
    target = None
    if user.default_team_id:
        result = await db.execute(select(Team).where(Team.id == user.default_team_id))
        target = result.scalar_one_or_none()
    if not target:
        target = user

    disabled = list(target.disabled_models or [])
    if enabled and model_id in disabled:
        disabled.remove(model_id)
    elif not enabled and model_id not in disabled:
        disabled.append(model_id)
    target.disabled_models = disabled
    db.add(target)
    await db.commit()
    return {"disabled_models": disabled}
