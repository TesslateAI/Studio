from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
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
