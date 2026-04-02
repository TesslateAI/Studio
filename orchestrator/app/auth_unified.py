"""
Unified Authentication Dependency

Accepts both JWT (browser sessions) and external API keys (tsk_* tokens).
JWT is tried first via fastapi-users' optional dependency; if it returns None
and the Authorization header carries a tsk_* token, we fall back to API-key
lookup. All downstream code receives the same User model regardless of auth
method.
"""

import hashlib
import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db
from .models import ExternalAPIKey, User
from .users import current_optional_user

logger = logging.getLogger(__name__)


async def get_authenticated_user(
    request: Request,
    jwt_user: User | None = Depends(current_optional_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Authenticate via JWT first; fall back to API key (tsk_*).

    Returns the same User model in both cases. For API-key users,
    ``user._api_key_record`` is set so scope enforcement can inspect it.
    """
    # Fast path: JWT worked — no extra DB call
    if jwt_user is not None:
        return jwt_user

    # Try API key from Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = auth_header.removeprefix("Bearer ").strip()
    if not token.startswith("tsk_"):
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Hash and lookup
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    result = await db.execute(
        select(ExternalAPIKey).where(
            ExternalAPIKey.key_hash == key_hash,
            ExternalAPIKey.is_active.is_(True),
        )
    )
    api_key_record = result.scalar_one_or_none()

    if not api_key_record:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if api_key_record.expires_at and api_key_record.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=401, detail="API key expired")

    # Update last_used_at (best-effort, non-blocking)
    try:
        api_key_record.last_used_at = datetime.now(UTC)
        await db.commit()
    except Exception:
        await db.rollback()

    # Load user
    user_result = await db.execute(select(User).where(User.id == api_key_record.user_id))
    user = user_result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    user._api_key_record = api_key_record  # type: ignore[attr-defined]
    return user


def enforce_project_scope(user: User, project_id: UUID) -> None:
    """
    For API-key users, verify the project is within the key's allowed scope.

    No-op for JWT users (they don't have ``_api_key_record``).
    Raises 403 if the API key is scoped to specific projects and the
    requested project is not among them.
    """
    api_key_record = getattr(user, "_api_key_record", None)
    if api_key_record is None:
        return  # JWT user — no scope restriction

    allowed_ids = api_key_record.project_ids
    if allowed_ids is None:
        return  # Key has access to all user's projects

    # project_ids is stored as JSON list of UUID strings
    allowed_str = {str(pid) for pid in allowed_ids}
    if str(project_id) not in allowed_str:
        raise HTTPException(
            status_code=403,
            detail="API key does not have access to this project",
        )
