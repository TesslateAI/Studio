"""
Authentication models for fastapi-users.
This module defines the User, OAuthAccount, and AccessToken models.
"""

import uuid
from datetime import datetime

from fastapi_users.db import SQLAlchemyBaseOAuthAccountTable, SQLAlchemyBaseUserTable
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.types import JSON

from app.types.guid import GUID

from .database import Base


class User(SQLAlchemyBaseUserTable[uuid.UUID], Base):
    """
    User model compatible with fastapi-users.

    Inherits base fields from SQLAlchemyBaseUserTable:
    - id (UUID): Primary key
    - email (str): User email, unique and indexed
    - hashed_password (str): Bcrypt hashed password
    - is_active (bool): Whether user account is active
    - is_superuser (bool): Whether user has admin privileges
    - is_verified (bool): Whether email is verified

    Additional custom fields for OpenSail:
    """

    __tablename__ = "users"

    # Override id to use our UUID type
    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4, index=True)

    # Custom fields (preserve existing schema)
    name: Mapped[str] = mapped_column(String, nullable=False)  # Display name
    username: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False
    )  # Login identifier
    slug: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False
    )  # URL-safe identifier

    # Creator-branded handle used in app runtime URLs
    # (``{container}-{app_handle}-{user_handle}.{app_domain}``). Nullable
    # until backfilled; unique once populated.
    handle: Mapped[str | None] = mapped_column(String(32), unique=True, index=True, nullable=True)

    # RBAC: user's active/default team
    default_team_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("teams.id", ondelete="SET NULL", use_alter=True, name="fk_users_default_team"),
        nullable=True,
    )

    # Creator payouts (Stripe Connect)
    creator_stripe_account_id: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # For receiving payouts

    # LiteLLM integration (usage tracking)
    litellm_api_key: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    litellm_user_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)

    # User preferences
    diagram_model: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Model for architecture diagrams
    theme_preset: Mapped[str | None] = mapped_column(
        String, nullable=True, default="default-dark"
    )  # UI theme preset
    chat_position: Mapped[str | None] = mapped_column(
        String(10), nullable=True, default="center"
    )  # Chat panel position: left, center, right
    disabled_models: Mapped[list | None] = mapped_column(
        JSON, nullable=True, default=list
    )  # Model IDs the user has disabled (hidden from chat selector)

    # Public profile fields
    avatar_url: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Profile picture URL or base64 data URI
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)  # Short bio/description
    twitter_handle: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # Twitter username
    github_username: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # GitHub username
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # Personal website

    # Referral system
    referral_code: Mapped[str | None] = mapped_column(
        String, unique=True, index=True, nullable=True
    )
    referred_by: Mapped[str | None] = mapped_column(String, nullable=True)  # Referrer code

    # Two-Factor Authentication
    two_fa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    two_fa_method: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # "email", "totp", etc.

    # Activity tracking
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Suspension fields (for admin user management)
    is_suspended: Mapped[bool] = mapped_column(default=False)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    suspended_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Soft delete fields (for admin user management)
    is_deleted: Mapped[bool] = mapped_column(default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    scheduled_hard_delete_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships (preserve existing relationships)
    projects = relationship("Project", back_populates="owner", cascade="all, delete-orphan")
    chats = relationship("Chat", back_populates="user", cascade="all, delete-orphan")
    agent_commands = relationship(
        "AgentCommandLog", back_populates="user", cascade="all, delete-orphan"
    )
    github_credential = relationship(
        "GitHubCredential", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    git_provider_credentials = relationship(
        "GitProviderCredential", back_populates="user", cascade="all, delete-orphan"
    )
    git_repositories = relationship(
        "GitRepository", back_populates="user", cascade="all, delete-orphan"
    )
    purchased_agents = relationship(
        "UserPurchasedAgent", back_populates="user", cascade="all, delete-orphan"
    )
    agent_reviews = relationship("AgentReview", back_populates="user", cascade="all, delete-orphan")
    purchased_bases = relationship(
        "UserPurchasedBase", back_populates="user", cascade="all, delete-orphan"
    )
    created_bases = relationship(
        "MarketplaceBase", foreign_keys="MarketplaceBase.created_by_user_id"
    )
    api_keys = relationship("UserAPIKey", back_populates="user", cascade="all, delete-orphan")
    custom_models = relationship(
        "UserCustomModel", back_populates="user", cascade="all, delete-orphan"
    )
    custom_providers = relationship(
        "UserProvider", back_populates="user", cascade="all, delete-orphan"
    )
    shell_sessions = relationship(
        "ShellSession", back_populates="user", cascade="all, delete-orphan"
    )
    feedback_posts = relationship(
        "FeedbackPost", back_populates="user", cascade="all, delete-orphan"
    )
    feedback_upvotes = relationship(
        "FeedbackUpvote", back_populates="user", cascade="all, delete-orphan"
    )
    feedback_comments = relationship(
        "FeedbackComment", back_populates="user", cascade="all, delete-orphan"
    )
    deployment_credentials = relationship(
        "DeploymentCredential", back_populates="user", cascade="all, delete-orphan"
    )
    deployments = relationship("Deployment", back_populates="user", cascade="all, delete-orphan")
    library_themes = relationship(
        "UserLibraryTheme", back_populates="user", cascade="all, delete-orphan"
    )

    # fastapi-users relationships
    oauth_accounts: Mapped[list["OAuthAccount"]] = relationship(
        "OAuthAccount", back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    access_tokens: Mapped[list["AccessToken"]] = relationship(
        "AccessToken", back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    # Compatibility property for existing code that uses is_admin
    @property
    def is_admin(self) -> bool:
        """Alias for is_superuser for backward compatibility."""
        return self.is_superuser

    @is_admin.setter
    def is_admin(self, value: bool):
        """Alias for is_superuser for backward compatibility."""
        self.is_superuser = value

    def __repr__(self):
        return f"<User {self.username} ({self.email})>"


class OAuthAccount(SQLAlchemyBaseOAuthAccountTable[uuid.UUID], Base):
    """
    OAuth account model for fastapi-users.

    Stores OAuth provider connections (Google, GitHub, etc.)

    Inherits base fields:
    - id (UUID): Primary key
    - user_id (UUID): Foreign key to users table
    - oauth_name (str): OAuth provider name (google, github, etc.)
    - access_token (str): OAuth access token
    - expires_at (int, optional): Token expiration timestamp
    - refresh_token (str, optional): OAuth refresh token
    - account_id (str): Provider-specific account ID
    - account_email (str): Email from OAuth provider
    """

    __tablename__ = "oauth_accounts"

    # Override id and user_id to use our UUID type
    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="cascade"), nullable=False
    )

    # Additional metadata
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationship
    user: Mapped[User] = relationship("User", back_populates="oauth_accounts")

    def __repr__(self):
        return f"<OAuthAccount {self.oauth_name} for user {self.user_id}>"


class RefreshToken(Base):
    """
    Refresh token for long-lived session persistence.

    Opaque token stored in DB, sent as httpOnly cookie. Validated by DB lookup.
    Supports rotation (each refresh revokes old + creates new) and revocation on logout.
    """

    __tablename__ = "refresh_tokens"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="cascade"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    # Relationship
    user: Mapped[User] = relationship("User")

    @property
    def is_valid(self) -> bool:
        from datetime import UTC

        return self.revoked_at is None and self.expires_at > datetime.now(tz=UTC)

    def __repr__(self):
        return f"<RefreshToken {self.token[:10]}... for user {self.user_id}>"


class AccessToken(Base):
    """
    Access token model for stateful authentication (Bearer token mode).

    This table is used when using Bearer token authentication strategy
    to store and validate access tokens in the database.
    """

    __tablename__ = "access_tokens"

    token: Mapped[str] = mapped_column(String(43), primary_key=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="cascade"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    user: Mapped[User] = relationship("User", back_populates="access_tokens")

    def __repr__(self):
        return f"<AccessToken {self.token[:10]}... for user {self.user_id}>"
