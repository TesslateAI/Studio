"""
Pydantic schemas for fastapi-users authentication.
"""

import uuid

from fastapi_users import schemas
from pydantic import BaseModel, Field


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
    stripe_customer_id: str | None = None
    total_spend: int = 0
    bundled_credits: int = 1000
    purchased_credits: int = 0
    litellm_api_key: str | None = None
    litellm_user_id: str | None = None
    diagram_model: str | None = None
    referral_code: str | None = None
    referred_by: str | None = None
    last_active_at: str | None = None

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
    username: str | None = Field(
        None,
        min_length=3,
        max_length=50,
        description="Unique username (auto-generated from email if not provided)",
    )
    referral_code: str | None = Field(None, description="Referral code from another user")


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
    name: str | None = Field(None, min_length=1, max_length=100)
    username: str | None = Field(None, min_length=3, max_length=50)
    subscription_tier: str | None = None
    diagram_model: str | None = None


class UserPreferences(BaseModel):
    """Schema for user preferences (subset of user data)."""

    diagram_model: str | None = None

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    """Response for login endpoint — either a JWT or a 2FA challenge."""

    access_token: str | None = None
    token_type: str = "bearer"
    requires_2fa: bool = False
    temp_token: str | None = None
    method: str | None = None  # "email" when 2FA is required


class TwoFAVerifyRequest(BaseModel):
    """Request body for verifying a 2FA code during login."""

    temp_token: str = Field(..., description="Temporary token from login response")
    code: str = Field(..., min_length=6, max_length=6, description="6-digit verification code")
