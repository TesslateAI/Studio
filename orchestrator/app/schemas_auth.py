"""
Pydantic schemas for fastapi-users authentication.
"""
from typing import Optional
import uuid
from fastapi_users import schemas
from pydantic import BaseModel, EmailStr, Field


class UserRead(schemas.BaseUser[uuid.UUID]):
    """
    Schema for reading user data (API responses).

    Inherits from fastapi-users BaseUser:
    - id: UUID
    - email: str
    - is_active: bool
    - is_superuser: bool
    - is_verified: bool
    """
    # Custom fields
    name: str
    username: str
    slug: str
    subscription_tier: str = "free"
    stripe_customer_id: Optional[str] = None
    total_spend: int = 0
    credits_balance: int = 0
    litellm_api_key: Optional[str] = None
    litellm_user_id: Optional[str] = None
    diagram_model: Optional[str] = None
    referral_code: Optional[str] = None
    referred_by: Optional[str] = None
    last_active_at: Optional[str] = None

    class Config:
        from_attributes = True


class UserCreate(schemas.BaseUserCreate):
    """
    Schema for creating a new user (registration).

    Inherits from fastapi-users BaseUserCreate:
    - email: EmailStr
    - password: str
    - is_active: bool (optional, default True)
    - is_superuser: bool (optional, default False)
    - is_verified: bool (optional, default False)
    """
    # Custom required fields
    name: str = Field(..., min_length=1, max_length=100, description="User's display name")

    # Optional fields with defaults
    username: Optional[str] = Field(None, min_length=3, max_length=50, description="Unique username (auto-generated from email if not provided)")
    referral_code: Optional[str] = Field(None, description="Referral code from another user")


class UserUpdate(schemas.BaseUserUpdate):
    """
    Schema for updating user data.

    Inherits from fastapi-users BaseUserUpdate:
    - password: Optional[str]
    - email: Optional[EmailStr]
    - is_active: Optional[bool]
    - is_superuser: Optional[bool]
    - is_verified: Optional[bool]
    """
    # Custom updatable fields
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    subscription_tier: Optional[str] = None
    diagram_model: Optional[str] = None


class UserPreferences(BaseModel):
    """Schema for user preferences (subset of user data)."""
    diagram_model: Optional[str] = None

    class Config:
        from_attributes = True
