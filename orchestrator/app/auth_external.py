"""
External API Key Authentication

Provides a FastAPI dependency for authenticating requests using external API keys.
Keys are SHA-256 hashed and stored in the external_api_keys table.

Also provides `require_api_scope()` — a dependency factory that enforces scoped
permissions on API-key-authenticated endpoints.
"""

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db
from .models import ExternalAPIKey, User
from .permissions import Permission, get_team_membership, has_permission

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
    if api_key_record.expires_at and api_key_record.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=401, detail="API key expired")

    # Update last_used_at (non-blocking, don't fail on error)
    try:
        api_key_record.last_used_at = datetime.now(UTC)
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


def require_api_scope(permission: Permission) -> Callable:
    """Dependency factory that checks an API key's scopes against the requested permission.

    Enforces two gates:
    1. If the key has explicit scopes, the requested permission must be in that list.
    2. The key owner's current role must still grant the permission (ceiling clamp).

    This is a drop-in replacement for ``get_external_api_user`` on endpoints that
    need scope enforcement.
    """

    async def _check_scope(
        user: User = Depends(get_external_api_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        key: ExternalAPIKey = user._api_key_record  # type: ignore

        # Gate 1: key-level scope check
        if key.scopes is not None and permission.value not in key.scopes:
            raise HTTPException(
                status_code=403,
                detail=f"API key lacks required scope: {permission.value}",
            )

        # Gate 2: owner's current role ceiling
        if user.default_team_id:
            membership = await get_team_membership(db, user.default_team_id, user.id)
            if membership and not has_permission(membership.role, permission):
                raise HTTPException(
                    status_code=403,
                    detail=f"Key owner's role no longer grants: {permission.value}",
                )

        # Attach the scope that was checked for audit logging
        user._api_scope_used = permission.value  # type: ignore

        # Non-blocking audit log entry for API key usage
        if user.default_team_id:
            try:
                from .services.audit_service import log_event

                await log_event(
                    db=db,
                    team_id=user.default_team_id,
                    user_id=user.id,
                    action="api_key.used",
                    resource_type="api_key",
                    resource_id=key.id,
                    details={
                        "key_prefix": key.key_prefix,
                        "key_name": key.name,
                        "scope_used": permission.value,
                    },
                )
            except Exception:
                logger.debug("Failed to log API key usage audit event", exc_info=True)

        return user

    return _check_scope
