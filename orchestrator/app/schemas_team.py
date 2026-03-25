"""Pydantic schemas for Teams, Memberships, Invitations, and Audit Logs."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ── Team ────────────────────────────────────────────────────────────────────


class TeamCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
    )


class TeamUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    slug: str | None = Field(
        None,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
    )
    avatar_url: str | None = None


class TeamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    avatar_url: str | None = None
    is_personal: bool
    created_by_id: UUID
    subscription_tier: str
    total_credits: int
    daily_credits: int
    bundled_credits: int
    purchased_credits: int
    signup_bonus_credits: int
    deployed_projects_count: int
    support_tier: str
    created_at: datetime


class TeamList(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    avatar_url: str | None = None
    is_personal: bool
    subscription_tier: str
    role: str | None = None  # populated from membership


# ── Membership ──────────────────────────────────────────────────────────────


class TeamMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    role: str
    is_active: bool
    joined_at: datetime
    # Joined from user
    user_name: str | None = None
    user_email: str | None = None
    user_avatar_url: str | None = None


class TeamMemberUpdate(BaseModel):
    role: str = Field(..., pattern=r"^(admin|editor|viewer)$")


# ── Invitations ─────────────────────────────────────────────────────────────


class InviteEmailRequest(BaseModel):
    email: EmailStr
    role: str = Field(..., pattern=r"^(admin|editor|viewer)$")


class InviteLinkRequest(BaseModel):
    role: str = Field(..., pattern=r"^(admin|editor|viewer)$")
    max_uses: int | None = None
    expires_in_days: int = Field(default=30, ge=1, le=365)


class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    role: str
    invite_type: str
    token: str
    expires_at: datetime
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None
    max_uses: int | None = None
    use_count: int
    created_at: datetime


class InviteAcceptResponse(BaseModel):
    team_id: UUID
    team_name: str
    team_slug: str
    role: str


class InviteDetailRead(BaseModel):
    """Public-facing invite details (for invite accept page)."""

    team_name: str
    team_slug: str
    team_avatar_url: str | None = None
    role: str
    invite_type: str
    expires_at: datetime
    is_valid: bool  # not expired, not revoked, not maxed


# ── Project Members ─────────────────────────────────────────────────────────


class ProjectMemberAdd(BaseModel):
    user_id: UUID
    role: str = Field(..., pattern=r"^(admin|editor|viewer)$")


class ProjectMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    role: str
    is_active: bool
    created_at: datetime
    user_name: str | None = None
    user_email: str | None = None


class ProjectMemberUpdate(BaseModel):
    role: str = Field(..., pattern=r"^(admin|editor|viewer)$")


# ── Audit Log ───────────────────────────────────────────────────────────────


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    project_id: UUID | None = None
    user_id: UUID
    action: str
    resource_type: str
    resource_id: UUID | None = None
    details: dict | None = None
    ip_address: str | None = None
    created_at: datetime


class AuditLogFilter(BaseModel):
    """Query parameters for audit log filtering."""

    action: str | None = None
    user_id: UUID | None = None
    project_id: UUID | None = None
    resource_type: str | None = None
    from_date: datetime | None = None
    to_date: datetime | None = None
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=50, ge=1, le=100)


# ── Team Billing ────────────────────────────────────────────────────────────


class TeamBillingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    subscription_tier: str
    total_credits: int
    daily_credits: int
    bundled_credits: int
    purchased_credits: int
    signup_bonus_credits: int
    credits_reset_date: datetime | None = None
    daily_credits_reset_date: datetime | None = None
    total_spend: int
    deployed_projects_count: int
    support_tier: str
