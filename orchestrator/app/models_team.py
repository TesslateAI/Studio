"""
Team and RBAC models for multi-user collaboration.

Provides the data layer for Teams, Memberships, Invitations, and Audit Logs.
See .claude/research/rbac-prd.md Section 4 for the full data model specification.
"""

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import JSON
from app.types.guid import GUID

from .database import Base


class Team(Base):
    """Team is the primary organizational unit. Owns projects and holds billing/credits."""

    __tablename__ = "teams"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    avatar_url = Column(Text, nullable=True)
    is_personal = Column(Boolean, nullable=False, default=False)
    created_by_id = Column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Billing (moved from User)
    subscription_tier = Column(String, nullable=False, default="free")
    stripe_customer_id = Column(String, nullable=True, unique=True, index=True)
    stripe_subscription_id = Column(String, nullable=True)
    total_spend = Column(Integer, nullable=False, default=0)
    bundled_credits = Column(Integer, nullable=False, default=0)
    purchased_credits = Column(Integer, nullable=False, default=0)
    daily_credits = Column(Integer, nullable=False, default=5)
    signup_bonus_credits = Column(Integer, nullable=False, default=0)
    signup_bonus_expires_at = Column(DateTime(timezone=True), nullable=True)
    credits_reset_date = Column(DateTime(timezone=True), nullable=True)
    daily_credits_reset_date = Column(DateTime(timezone=True), nullable=True)
    support_tier = Column(String(20), nullable=False, default="community")
    deployed_projects_count = Column(Integer, nullable=False, default=0)

    # Appearance
    theme_preset = Column(String, nullable=True, default="default-dark")

    # Model preferences
    disabled_models = Column(JSON, nullable=True, default=list)  # Model IDs hidden from chat selector

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    memberships = relationship("TeamMembership", back_populates="team", lazy="selectin")
    projects = relationship(
        "Project", back_populates="team", foreign_keys="[Project.team_id]", lazy="noload"
    )
    invitations = relationship("TeamInvitation", back_populates="team", lazy="noload")

    @property
    def total_credits(self) -> int:
        """Total available credits (daily + bundled + signup_bonus + purchased)."""
        from datetime import UTC
        from datetime import datetime as dt

        bonus = self.signup_bonus_credits or 0
        if self.signup_bonus_expires_at and dt.now(UTC) > self.signup_bonus_expires_at:
            bonus = 0
        return (
            (self.daily_credits or 0)
            + (self.bundled_credits or 0)
            + bonus
            + (self.purchased_credits or 0)
        )


class TeamMembership(Base):
    """Links a user to a team with a role (admin/editor/viewer)."""

    __tablename__ = "team_memberships"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    team_id = Column(GUID(), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)  # 'admin', 'editor', 'viewer'
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    invited_by_id = Column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    joined_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_memberships_team_user"),
        Index("ix_team_memberships_user_id", "user_id"),
    )

    # Relationships
    team = relationship("Team", back_populates="memberships")
    user = relationship("User", foreign_keys=[user_id])


class ProjectMembership(Base):
    """Per-project role override. Allows elevating or restricting a member's access on a specific project."""

    __tablename__ = "project_memberships"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)  # 'admin', 'editor', 'viewer'
    granted_by_id = Column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_memberships_project_user"),
        Index("ix_project_memberships_user_id", "user_id"),
    )

    # Relationships
    project = relationship("Project", back_populates="project_memberships")
    user = relationship("User", foreign_keys=[user_id])


class TeamInvitation(Base):
    """Invitation to join a team, via email or shareable link."""

    __tablename__ = "team_invitations"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    team_id = Column(GUID(), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    email = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False)  # 'admin', 'editor', 'viewer'
    token = Column(String(64), unique=True, nullable=False, index=True)
    invite_type = Column(String(20), nullable=False, default="email")  # 'email', 'link'
    invited_by_id = Column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=False
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    accepted_by_id = Column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    max_uses = Column(Integer, nullable=True)  # for link invites (null = unlimited)
    use_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_team_invitations_team_email", "team_id", "email"),)

    # Relationships
    team = relationship("Team", back_populates="invitations")
    invited_by = relationship("User", foreign_keys=[invited_by_id])


class AuditLog(Base):
    """Immutable audit trail for team and project events."""

    __tablename__ = "audit_logs"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    team_id = Column(GUID(), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(
        GUID(), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    user_id = Column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=False
    )
    action = Column(String(100), nullable=False)  # e.g., 'member.invited', 'project.deleted'
    resource_type = Column(String(50), nullable=False)  # e.g., 'team', 'project', 'container'
    resource_id = Column(GUID(), nullable=True)
    details = Column(JSON, nullable=True)  # action-specific metadata
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6
    user_agent = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships (for eager loading in audit queries)
    project = relationship("Project", foreign_keys=[project_id], lazy="noload")
    user = relationship("User", foreign_keys=[user_id], lazy="noload")

    __table_args__ = (
        Index("ix_audit_logs_team_created", "team_id", "created_at"),
        Index("ix_audit_logs_project_created", "project_id", "created_at"),
        Index("ix_audit_logs_user_created", "user_id", "created_at"),
        Index("ix_audit_logs_action", "action"),
    )
