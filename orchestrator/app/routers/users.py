from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from ..database import get_db
from ..models import User
from ..users import current_active_user, current_superuser
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class UserPreferencesUpdate(BaseModel):
    diagram_model: str | None = None


class UserPreferencesResponse(BaseModel):
    diagram_model: str | None = None


class UserProfileUpdate(BaseModel):
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    twitter_handle: Optional[str] = None
    github_username: Optional[str] = None
    website_url: Optional[str] = None


@router.get("/preferences", response_model=UserPreferencesResponse)
async def get_user_preferences(
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user preferences including diagram generation model."""
    return UserPreferencesResponse(
        diagram_model=current_user.diagram_model
    )


@router.patch("/preferences")
async def update_user_preferences(
    preferences: UserPreferencesUpdate,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Update user preferences."""
    try:
        # Update diagram model if provided
        if preferences.diagram_model is not None:
            current_user.diagram_model = preferences.diagram_model
            logger.info(f"Updated diagram_model for user {current_user.id} to {preferences.diagram_model}")

        await db.commit()
        await db.refresh(current_user)

        return {
            "message": "Preferences updated successfully",
            "diagram_model": current_user.diagram_model
        }
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to update user preferences: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update preferences: {str(e)}")


@router.get("/profile")
async def get_user_profile(
    current_user: User = Depends(current_active_user)
):
    """Get current user's profile information."""
    return {
        "id": str(current_user.id),
        "email": current_user.email,
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
    db: AsyncSession = Depends(get_db)
):
    """Update current user's profile information."""
    try:
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
            "name": current_user.name,
            "avatar_url": current_user.avatar_url,
            "bio": current_user.bio,
            "twitter_handle": current_user.twitter_handle,
            "github_username": current_user.github_username,
            "website_url": current_user.website_url,
        }
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to update user profile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update profile: {str(e)}")
