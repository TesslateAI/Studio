"""
Authentication models for fastapi-users.
This module defines the User, OAuthAccount, and AccessToken models.
"""
from datetime import datetime
from typing import Optional
import uuid

from fastapi_users.db import SQLAlchemyBaseUserTable, SQLAlchemyBaseOAuthAccountTable
from sqlalchemy import Column, String, DateTime, Boolean, Integer, ForeignKey, Text
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID

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

    Additional custom fields for Tesslate Studio:
    """
    __tablename__ = "users"

    # Override id to use our UUID type
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )

    # Custom fields (preserve existing schema)
    name: Mapped[str] = mapped_column(String, nullable=False)  # Display name
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)  # Login identifier
    slug: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)  # URL-safe identifier

    # Subscription & billing
    subscription_tier: Mapped[str] = mapped_column(String, default="free")  # free, pro, enterprise
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Active subscription ID
    total_spend: Mapped[int] = mapped_column(Integer, default=0)  # In cents for precision
    credits_balance: Mapped[int] = mapped_column(Integer, default=0)  # In cents (prepaid credits)
    deployed_projects_count: Mapped[int] = mapped_column(Integer, default=0)  # Number of deployed projects

    # Creator payouts (Stripe Connect)
    creator_stripe_account_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # For receiving payouts

    # LiteLLM integration (usage tracking)
    litellm_api_key: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)
    litellm_user_id: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)

    # User preferences
    diagram_model: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Model for architecture diagrams

    # Referral system
    referral_code: Mapped[Optional[str]] = mapped_column(String, unique=True, index=True, nullable=True)
    referred_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Referrer code

    # Activity tracking
    last_active_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships (preserve existing relationships)
    projects = relationship("Project", back_populates="owner", cascade="all, delete-orphan")
    chats = relationship("Chat", back_populates="user", cascade="all, delete-orphan")
    agent_commands = relationship("AgentCommandLog", back_populates="user", cascade="all, delete-orphan")
    github_credential = relationship("GitHubCredential", back_populates="user", uselist=False, cascade="all, delete-orphan")
    git_repositories = relationship("GitRepository", back_populates="user", cascade="all, delete-orphan")
    purchased_agents = relationship("UserPurchasedAgent", back_populates="user", cascade="all, delete-orphan")
    agent_reviews = relationship("AgentReview", back_populates="user", cascade="all, delete-orphan")
    purchased_bases = relationship("UserPurchasedBase", back_populates="user", cascade="all, delete-orphan")
    api_keys = relationship("UserAPIKey", back_populates="user", cascade="all, delete-orphan")
    custom_models = relationship("UserCustomModel", back_populates="user", cascade="all, delete-orphan")
    shell_sessions = relationship("ShellSession", back_populates="user", cascade="all, delete-orphan")
    feedback_posts = relationship("FeedbackPost", back_populates="user", cascade="all, delete-orphan")
    feedback_upvotes = relationship("FeedbackUpvote", back_populates="user", cascade="all, delete-orphan")
    feedback_comments = relationship("FeedbackComment", back_populates="user", cascade="all, delete-orphan")
    deployment_credentials = relationship("DeploymentCredential", back_populates="user", cascade="all, delete-orphan")
    deployments = relationship("Deployment", back_populates="user", cascade="all, delete-orphan")

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
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="cascade"), nullable=False
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


class AccessToken(Base):
    """
    Access token model for stateful authentication (Bearer token mode).

    This table is used when using Bearer token authentication strategy
    to store and validate access tokens in the database.
    """
    __tablename__ = "access_tokens"

    token: Mapped[str] = mapped_column(String(43), primary_key=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="cascade"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    user: Mapped[User] = relationship("User", back_populates="access_tokens")

    def __repr__(self):
        return f"<AccessToken {self.token[:10]}... for user {self.user_id}>"
