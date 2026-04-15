"""Cloud pairing endpoints (auth status, token get/set/clear) and local-auth bootstrap."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...database import get_db
from ...models import User
from ...services import token_store
from ...services.desktop_auth import desktop_loopback_only, desktop_loopback_or_session

logger = logging.getLogger(__name__)

router = APIRouter()


class CloudTokenBody(BaseModel):
    token: str = Field(..., min_length=1, max_length=512)


# ---------------------------------------------------------------------------
# Desktop-local auto-login
# ---------------------------------------------------------------------------

_LOCAL_USER_EMAIL = "local@desktop.tesslate.app"
_LOCAL_USER_NAME = "Local User"
_LOCAL_USER_USERNAME = "local_user"
_DESKTOP_TOKEN_LIFETIME_DAYS = 365


async def _ensure_personal_team(user: User, db: AsyncSession) -> None:
    """Create a personal Team + admin TeamMembership if the user has none."""
    import uuid as _uuid

    from ...models_team import Team, TeamMembership  # noqa: PLC0415

    if user.default_team_id is not None:
        return

    team_id = _uuid.uuid4()
    # Use a stable slug derived from the user id so re-runs are idempotent.
    team_slug = f"local-team-{str(user.id)[:8]}"
    team = Team(
        id=team_id,
        name="Local Team",
        slug=team_slug,
        is_personal=True,
        created_by_id=user.id,
        subscription_tier="free",
        daily_credits=0,
        signup_bonus_credits=0,
    )
    db.add(team)
    await db.flush()

    membership = TeamMembership(
        team_id=team_id,
        user_id=user.id,
        role="admin",
    )
    db.add(membership)
    user.default_team_id = team_id
    await db.commit()
    logger.info("Created personal team for local desktop user: %s", team_slug)


async def _get_or_create_local_user(db: AsyncSession) -> User:
    """Return the fixed local desktop user, creating it in SQLite if absent."""
    import secrets

    from nanoid import generate  # noqa: PLC0415

    result = await db.execute(select(User).where(User.email == _LOCAL_USER_EMAIL))
    existing = result.scalar_one_or_none()
    if existing is not None:
        await _ensure_personal_team(existing, db)  # repair if missing
        return existing

    # First launch — provision the local user.
    username_suffix = generate(size=6)
    username = f"local_user_{username_suffix}"
    slug = f"local-user-{username_suffix}"
    referral_code = generate(size=8).upper()

    from fastapi_users.password import PasswordHelper  # noqa: PLC0415

    ph = PasswordHelper()
    # Random password — desktop local user authenticates via token, not password.
    hashed_pw = ph.hash(secrets.token_urlsafe(32))

    user = User(
        id=uuid.uuid4(),
        email=_LOCAL_USER_EMAIL,
        hashed_password=hashed_pw,
        name=_LOCAL_USER_NAME,
        username=username,
        slug=slug,
        referral_code=referral_code,
        is_active=True,
        is_superuser=False,
        is_verified=True,
        subscription_tier="free",
        total_spend=0,
        bundled_credits=0,
        purchased_credits=0,
        daily_credits=get_settings().tier_daily_credits_free,
        daily_credits_reset_date=datetime.now(UTC),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("Provisioned local desktop user: %s", _LOCAL_USER_EMAIL)
    await _ensure_personal_team(user, db)  # create team for new user
    return user


async def _issue_desktop_token(user: User) -> str:
    """Issue a long-lived JWT for the local desktop user."""
    from jose import jwt as jose_jwt  # noqa: PLC0415

    settings = get_settings()
    data = {
        "sub": str(user.id),
        "aud": "fastapi-users:auth",
        "is_admin": user.is_superuser,
        "exp": datetime.now(UTC) + timedelta(days=_DESKTOP_TOKEN_LIFETIME_DAYS),
    }
    return jose_jwt.encode(data, settings.secret_key, algorithm=settings.algorithm)


@router.get("/local-auth")
async def get_local_auth(
    _: None = Depends(desktop_loopback_only),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Return a long-lived JWT for the local desktop user.

    The Tauri host calls this immediately after the sidecar becomes ready
    and injects the token into the WebView so the frontend never needs to
    go through the registration / login flow on a local-only desktop
    deployment.

    Protected by the per-launch sidecar bearer — only the Tauri host can
    call this endpoint.
    """
    user = await _get_or_create_local_user(db)
    token = await _issue_desktop_token(user)
    return {"token": token}


@router.get("/auth/status")
async def auth_status(_user: User = Depends(desktop_loopback_or_session)) -> dict[str, Any]:
    """Cheap, network-free pairing probe."""
    return {
        "paired": token_store.is_paired(),
        "cloud_url": get_settings().tesslate_cloud_url,
    }


@router.post("/auth/token")
async def set_auth_token(
    body: CloudTokenBody,
    _user: User = Depends(desktop_loopback_or_session),
) -> dict[str, Any]:
    """Persist a cloud bearer token (called by the Tauri deep-link handler)."""
    token_store.set_cloud_token(body.token)
    return {"paired": True}


@router.delete("/auth/token")
async def clear_auth_token(_user: User = Depends(desktop_loopback_or_session)) -> dict[str, Any]:
    """Forget the cloud bearer token (desktop logout)."""
    token_store.clear_cloud_token()
    return {"paired": False}
