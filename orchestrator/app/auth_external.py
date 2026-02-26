"""
External API Key Authentication

Provides a FastAPI dependency for authenticating requests using external API keys.
Keys are SHA-256 hashed and stored in the external_api_keys table.
"""

import hashlib
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db
from .models import ExternalAPIKey, User

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


async def get_external_api_user(
    api_key: str | None = Security(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Authenticate request using external API key.

    Expects header: Authorization: Bearer tsk_...
    """
    if not api_key:
        raise HTTPException(status_code=401, detail="API key required")

    # Strip "Bearer " prefix
    if api_key.startswith("Bearer "):
        api_key = api_key[7:]

    # Hash the key and look it up
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    result = await db.execute(
        select(ExternalAPIKey).where(
            ExternalAPIKey.key_hash == key_hash,
            ExternalAPIKey.is_active.is_(True),
        )
    )
    api_key_record = result.scalar_one_or_none()

    if not api_key_record:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Check expiration
    if api_key_record.expires_at and api_key_record.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="API key expired")

    # Update last_used_at (non-blocking, don't fail on error)
    try:
        api_key_record.last_used_at = datetime.now(timezone.utc)
        await db.commit()
    except Exception:
        pass

    # Load the user
    user_result = await db.execute(
        select(User).where(User.id == api_key_record.user_id)
    )
    user = user_result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    # Attach key metadata to user for scope checking
    user._api_key_record = api_key_record  # type: ignore
    return user
