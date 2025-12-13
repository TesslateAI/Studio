"""
API Keys and Secrets Management endpoints.
Handles storage and management of user API keys for various providers.
"""

from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
import base64
import logging

from ..database import get_db
from ..models import User, UserAPIKey
from ..users import current_active_user, current_superuser

logger = logging.getLogger(__name__)
router = APIRouter()


# Simple encoding for now - in production, use proper encryption (e.g., Fernet, AWS KMS, etc.)
def encode_key(key: str) -> str:
    """Encode API key for storage. In production, use proper encryption."""
    # Strip whitespace before encoding to prevent issues
    return base64.b64encode(key.strip().encode()).decode()


def decode_key(encoded: str) -> str:
    """Decode API key from storage. In production, use proper decryption."""
    # Strip whitespace after decoding to handle any encoding issues
    return base64.b64decode(encoded.encode()).decode().strip()


@router.get("/api-keys")
async def list_api_keys(
    provider: Optional[str] = None,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all API keys for the current user.
    """
    query = select(UserAPIKey).where(
        UserAPIKey.user_id == current_user.id,
        UserAPIKey.is_active == True
    )

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
                "key_preview": decode_key(key.encrypted_value)[:8] + "..." if key.encrypted_value else None,
                "provider_metadata": key.provider_metadata,
                "expires_at": key.expires_at.isoformat() if key.expires_at else None,
                "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
                "created_at": key.created_at.isoformat()
            }
            for key in api_keys
        ]
    }


@router.post("/api-keys")
async def add_api_key(
    provider: str = Body(..., description="Provider name (openrouter, anthropic, openai, google, etc.)"),
    api_key: str = Body(..., description="The API key value"),
    auth_type: str = Body(default="api_key", description="Authentication type"),
    key_name: Optional[str] = Body(None, description="Optional name for this key"),
    provider_metadata: Optional[dict] = Body(default={}, description="Provider-specific metadata"),
    expires_at: Optional[str] = Body(None, description="Optional expiration date"),
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Add a new API key for a provider.
    """
    # Check if key with same provider and name already exists
    existing_query = select(UserAPIKey).where(
        UserAPIKey.user_id == current_user.id,
        UserAPIKey.provider == provider,
        UserAPIKey.key_name == key_name
    )
    result = await db.execute(existing_query)
    existing_key = result.scalar_one_or_none()

    if existing_key:
        if existing_key.is_active:
            raise HTTPException(
                status_code=400,
                detail=f"API key for {provider}" + (f" with name '{key_name}'" if key_name else "") + " already exists"
            )
        else:
            # Reactivate existing key
            existing_key.encrypted_value = encode_key(api_key)
            existing_key.is_active = True
            existing_key.provider_metadata = provider_metadata
            existing_key.expires_at = datetime.fromisoformat(expires_at) if expires_at else None
            existing_key.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(existing_key)
            return {
                "message": "API key reactivated",
                "key_id": existing_key.id,
                "success": True
            }

    # Create new API key
    new_key = UserAPIKey(
        user_id=current_user.id,
        provider=provider,
        auth_type=auth_type,
        key_name=key_name,
        encrypted_value=encode_key(api_key),
        provider_metadata=provider_metadata or {},
        expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
        is_active=True
    )

    db.add(new_key)
    await db.commit()
    await db.refresh(new_key)

    return {
        "message": "API key added successfully",
        "key_id": new_key.id,
        "provider": provider,
        "success": True
    }


@router.put("/api-keys/{key_id}")
async def update_api_key(
    key_id: str,
    api_key: Optional[str] = Body(None, description="New API key value"),
    key_name: Optional[str] = Body(None, description="New name for this key"),
    provider_metadata: Optional[dict] = Body(None, description="Updated metadata"),
    expires_at: Optional[str] = Body(None, description="Updated expiration date"),
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update an existing API key.
    """
    query = select(UserAPIKey).where(
        UserAPIKey.id == key_id,
        UserAPIKey.user_id == current_user.id
    )
    result = await db.execute(query)
    key_record = result.scalar_one_or_none()

    if not key_record:
        raise HTTPException(status_code=404, detail="API key not found")

    # Update fields
    if api_key:
        key_record.encrypted_value = encode_key(api_key)
    if key_name is not None:
        key_record.key_name = key_name
    if provider_metadata is not None:
        key_record.provider_metadata = provider_metadata
    if expires_at is not None:
        key_record.expires_at = datetime.fromisoformat(expires_at) if expires_at else None

    key_record.updated_at = datetime.now(timezone.utc)

    await db.commit()

    return {
        "message": "API key updated successfully",
        "key_id": key_id,
        "success": True
    }


@router.delete("/api-keys/{key_id}")
async def delete_api_key(
    key_id: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete (deactivate) an API key.
    """
    query = select(UserAPIKey).where(
        UserAPIKey.id == key_id,
        UserAPIKey.user_id == current_user.id
    )
    result = await db.execute(query)
    key_record = result.scalar_one_or_none()

    if not key_record:
        raise HTTPException(status_code=404, detail="API key not found")

    # Soft delete
    key_record.is_active = False
    key_record.updated_at = datetime.now(timezone.utc)

    await db.commit()

    return {
        "message": "API key deleted successfully",
        "success": True
    }


@router.get("/api-keys/{key_id}")
async def get_api_key(
    key_id: str,
    reveal: bool = False,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a specific API key. Use reveal=true to get the full key value.
    """
    query = select(UserAPIKey).where(
        UserAPIKey.id == key_id,
        UserAPIKey.user_id == current_user.id
    )
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
        "key_value": decoded_key if reveal else None,
        "key_preview": decoded_key[:8] + "..." if decoded_key and not reveal else None,
        "provider_metadata": key_record.provider_metadata,
        "expires_at": key_record.expires_at.isoformat() if key_record.expires_at else None,
        "last_used_at": key_record.last_used_at.isoformat() if key_record.last_used_at else None,
        "created_at": key_record.created_at.isoformat(),
        "is_active": key_record.is_active
    }


@router.get("/providers")
async def list_supported_providers(
    current_user: User = Depends(current_active_user)
):
    """
    List all supported providers and their configuration.
    """
    providers = [
        {
            "id": "openrouter",
            "name": "OpenRouter",
            "description": "Access to 200+ AI models through a unified API",
            "auth_type": "api_key",
            "website": "https://openrouter.ai",
            "requires_key": True,
            "supports_oauth": False
        },
        {
            "id": "google",
            "name": "Google Cloud",
            "description": "Gemini and other Google AI models",
            "auth_type": "oauth_token",
            "website": "https://cloud.google.com",
            "requires_key": False,
            "supports_oauth": True
        },
        {
            "id": "github",
            "name": "GitHub",
            "description": "GitHub Copilot and Models",
            "auth_type": "personal_access_token",
            "website": "https://github.com",
            "requires_key": True,
            "supports_oauth": True
        }
    ]

    return {"providers": providers}
