import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User
from ..services.apps.reserved_handles import (
    is_reserved as is_reserved_handle,
    is_valid_handle_format,
)
from ..username_validation import normalize_username, validate_username
from ..users import current_active_user

logger = logging.getLogger(__name__)

router = APIRouter()


class UserPreferencesUpdate(BaseModel):
    diagram_model: str | None = None
    theme_preset: str | None = None
    chat_position: str | None = None  # "left" | "center" | "right"


class UserPreferencesResponse(BaseModel):
    diagram_model: str | None = None
    theme_preset: str | None = None
    chat_position: str | None = None


AVATAR_URL_MAX_LENGTH = 512_000  # 500KB - generous limit for base64 data URIs


class UserProfileUpdate(BaseModel):
    username: str | None = None
    name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    twitter_handle: str | None = None
    github_username: str | None = None
    website_url: str | None = None

    @field_validator("username")
    @classmethod
    def validate_username_format(cls, v: str | None) -> str | None:
        if v is None:
            return v
        normalized = normalize_username(v)
        valid, error = validate_username(normalized)
        if not valid:
            raise ValueError(error)
        return normalized

    @field_validator("avatar_url")
    @classmethod
    def validate_avatar_url_length(cls, v: str | None) -> str | None:
        if v is not None and len(v) > AVATAR_URL_MAX_LENGTH:
            raise ValueError(
                f"avatar_url exceeds maximum length of {AVATAR_URL_MAX_LENGTH} characters"
            )
        return v


@router.get("/preferences", response_model=UserPreferencesResponse)
async def get_user_preferences(
    current_user: User = Depends(current_active_user), db: AsyncSession = Depends(get_db)
):
    """Get user preferences including diagram generation model, theme, and chat position."""
    # Use the active team's theme if available, falling back to user's theme
    theme = current_user.theme_preset or "default-dark"
    if current_user.default_team_id:
        from ..models_team import Team

        team_result = await db.execute(
            select(Team).where(Team.id == current_user.default_team_id)
        )
        team = team_result.scalar_one_or_none()
        if team and team.theme_preset:
            theme = team.theme_preset

    return UserPreferencesResponse(
        diagram_model=current_user.diagram_model,
        theme_preset=theme,
        chat_position=current_user.chat_position or "center",
    )


@router.patch("/preferences")
async def update_user_preferences(
    preferences: UserPreferencesUpdate,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update user preferences."""
    try:
        # Update diagram model if provided
        if preferences.diagram_model is not None:
            current_user.diagram_model = preferences.diagram_model
            logger.info(
                f"Updated diagram_model for user {current_user.id} to {preferences.diagram_model}"
            )

        # Update theme preset if provided (save to both user and active team)
        if preferences.theme_preset is not None:
            current_user.theme_preset = preferences.theme_preset
            if current_user.default_team_id:
                from ..models_team import Team

                team_result = await db.execute(
                    select(Team).where(Team.id == current_user.default_team_id)
                )
                team = team_result.scalar_one_or_none()
                if team:
                    team.theme_preset = preferences.theme_preset
            logger.info(
                f"Updated theme_preset for user {current_user.id} to {preferences.theme_preset}"
            )

        # Update chat position if provided
        if preferences.chat_position is not None:
            # Validate chat position value
            if preferences.chat_position not in ("left", "center", "right"):
                raise HTTPException(
                    status_code=400, detail="chat_position must be 'left', 'center', or 'right'"
                )
            current_user.chat_position = preferences.chat_position
            logger.info(
                f"Updated chat_position for user {current_user.id} to {preferences.chat_position}"
            )

        await db.commit()
        await db.refresh(current_user)

        return {
            "message": "Preferences updated successfully",
            "diagram_model": current_user.diagram_model,
            "theme_preset": current_user.theme_preset or "default-dark",
            "chat_position": current_user.chat_position or "center",
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to update user preferences: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to update preferences: {str(e)}"
        ) from e


class UserHandleUpdate(BaseModel):
    handle: str

    @field_validator("handle")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return (v or "").lower().strip()


@router.patch("/me/handle")
async def update_user_handle(
    payload: UserHandleUpdate,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Set the creator-branded handle used in app runtime URLs.

    Returns 409 when the requested handle is reserved or already taken.
    Format: ``^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$``.
    """
    handle = payload.handle
    if not is_valid_handle_format(handle, max_length=32):
        raise HTTPException(
            status_code=400,
            detail=(
                "Handle must be 3-32 chars, lowercase alphanumeric or hyphens, "
                "starting and ending with an alphanumeric character."
            ),
        )
    if is_reserved_handle(handle):
        raise HTTPException(status_code=409, detail="Handle is not available")

    existing = await db.execute(
        select(User.id).where(
            func.lower(User.handle) == handle, User.id != current_user.id
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Handle is already taken")

    current_user.handle = handle
    await db.commit()
    await db.refresh(current_user)
    return {"handle": current_user.handle}


@router.get("/profile")
async def get_user_profile(current_user: User = Depends(current_active_user)):
    """Get current user's profile information."""
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "username": current_user.username,
        "name": current_user.name,
        "avatar_url": current_user.avatar_url,
        "bio": current_user.bio,
        "twitter_handle": current_user.twitter_handle,
        "github_username": current_user.github_username,
        "website_url": current_user.website_url,
    }


@router.patch("/profile")
async def update_user_profile(
    profile: UserProfileUpdate,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user's profile information."""
    try:
        # Handle username change with uniqueness check
        if profile.username is not None:
            normalized = normalize_username(profile.username)
            valid, error = validate_username(normalized)
            if not valid:
                raise HTTPException(status_code=400, detail=error)

            # Check uniqueness (exclude current user to avoid self-conflict)
            existing = await db.execute(
                select(User.id).where(
                    func.lower(User.username) == normalized,
                    User.id != current_user.id,
                )
            )
            if existing.scalar_one_or_none() is not None:
                raise HTTPException(status_code=409, detail="Username is already taken")

            current_user.username = normalized

        # Update fields if provided
        if profile.name is not None:
            current_user.name = profile.name
        if profile.avatar_url is not None:
            current_user.avatar_url = profile.avatar_url
        if profile.bio is not None:
            current_user.bio = profile.bio
        if profile.twitter_handle is not None:
            current_user.twitter_handle = profile.twitter_handle
        if profile.github_username is not None:
            current_user.github_username = profile.github_username
        if profile.website_url is not None:
            current_user.website_url = profile.website_url

        await db.commit()
        await db.refresh(current_user)

        logger.info(f"Updated profile for user {current_user.id}")

        return {
            "message": "Profile updated successfully",
            "id": str(current_user.id),
            "email": current_user.email,
            "username": current_user.username,
            "name": current_user.name,
            "avatar_url": current_user.avatar_url,
            "bio": current_user.bio,
            "twitter_handle": current_user.twitter_handle,
            "github_username": current_user.github_username,
            "website_url": current_user.website_url,
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to update user profile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update profile: {str(e)}") from e
