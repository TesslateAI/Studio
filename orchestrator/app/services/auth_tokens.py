"""
Token pair issuance and refresh cookie management.

Issues short-lived access JWTs (15 min) alongside long-lived opaque
refresh tokens (14 days) stored in the database. The refresh token
is delivered as an httpOnly cookie.
"""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models_auth import RefreshToken, User
from ..users import get_jwt_strategy

settings = get_settings()

REFRESH_COOKIE_NAME = "tesslate_refresh"
REFRESH_TOKEN_DAYS = settings.refresh_token_expire_days  # 14


def _set_refresh_cookie(response: Response, token: str) -> None:
    """Set the refresh token httpOnly cookie on a response."""
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=REFRESH_TOKEN_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=cast(Literal["lax", "strict", "none"], settings.cookie_samesite),
        domain=settings.cookie_domain if settings.cookie_domain else None,
        path="/api/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Delete the refresh token cookie."""
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=cast(Literal["lax", "strict", "none"], settings.cookie_samesite),
        domain=settings.cookie_domain if settings.cookie_domain else None,
        path="/api/auth",
    )


def _clear_access_cookie(response: Response) -> None:
    """Delete the access token cookie (tesslate_auth)."""
    response.delete_cookie(
        key="tesslate_auth",
        httponly=True,
        secure=settings.cookie_secure,
        samesite=cast(Literal["lax", "strict", "none"], settings.cookie_samesite),
        domain=settings.cookie_domain if settings.cookie_domain else None,
        path="/",
    )


async def issue_token_pair(
    db: AsyncSession,
    user: User,
    response: Response,
    request: Request,
) -> str:
    """
    Issue an access + refresh token pair.

    - Creates a short-lived access JWT (returned to caller)
    - Creates an opaque refresh token (persisted in DB, set as httpOnly cookie)

    Returns the access_token string.
    """
    # 1. Access token (stateless JWT, 15 min)
    jwt_strategy = get_jwt_strategy()
    access_token = await jwt_strategy.write_token(user)

    # 2. Refresh token (opaque, DB-backed, 14 days)
    refresh_token_value = secrets.token_urlsafe(48)
    refresh_row = RefreshToken(
        token=refresh_token_value,
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_DAYS),
        user_agent=request.headers.get("User-Agent", "")[:512],
        ip_address=(
            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or (request.client.host if request.client else None)
        ),
    )
    db.add(refresh_row)
    await db.flush()

    # 3. Set refresh cookie
    _set_refresh_cookie(response, refresh_token_value)

    return access_token
