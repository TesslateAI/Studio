"""
Centralized RBAC permission system for Tesslate Studio.

Provides the Permission enum, role-to-permission mappings, and core access-check
functions used across all routers. This module is the single source of truth for
"who can do what" — routers call into these helpers instead of hand-rolling
owner_id comparisons.

See .claude/research/rbac-prd.md for the full RBAC specification.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from .models import Project
    from .models_team import TeamMembership

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Permission Enum
# ---------------------------------------------------------------------------


class Permission(StrEnum):
    """Every granular permission in the system. Values are dot-delimited for
    readability in logs and audit trails."""

    # Team-level
    TEAM_VIEW = "team.view"
    TEAM_EDIT = "team.edit"
    TEAM_DELETE = "team.delete"
    TEAM_INVITE = "team.invite"
    TEAM_REMOVE_MEMBER = "team.remove_member"
    TEAM_CHANGE_ROLE = "team.change_role"
    BILLING_VIEW = "billing.view"
    BILLING_MANAGE = "billing.manage"
    BILLING_USAGE = "billing.usage"

    # Project-level
    PROJECT_LIST = "project.list"
    PROJECT_CREATE = "project.create"
    PROJECT_VIEW = "project.view"
    PROJECT_EDIT = "project.edit"
    PROJECT_DELETE = "project.delete"
    PROJECT_SETTINGS = "project.settings"

    # File
    FILE_READ = "file.read"
    FILE_WRITE = "file.write"
    FILE_DELETE = "file.delete"

    # Container
    CONTAINER_VIEW = "container.view"
    CONTAINER_CREATE = "container.create"
    CONTAINER_EDIT = "container.edit"
    CONTAINER_DELETE = "container.delete"
    CONTAINER_START_STOP = "container.start_stop"

    # Chat / Agent
    CHAT_VIEW = "chat.view"
    CHAT_SEND = "chat.send"
    CHAT_DELETE = "chat.delete"

    # Deployment
    DEPLOYMENT_VIEW = "deployment.view"
    DEPLOYMENT_CREATE = "deployment.create"
    DEPLOYMENT_DELETE = "deployment.delete"

    # Git
    GIT_VIEW = "git.view"
    GIT_WRITE = "git.write"

    # Kanban
    KANBAN_VIEW = "kanban.view"
    KANBAN_EDIT = "kanban.edit"

    # Snapshot
    SNAPSHOT_VIEW = "snapshot.view"
    SNAPSHOT_CREATE = "snapshot.create"
    SNAPSHOT_RESTORE = "snapshot.restore"

    # Terminal
    TERMINAL_ACCESS = "terminal.access"

    # Credentials
    CREDENTIALS_VIEW = "credentials.view"
    CREDENTIALS_MANAGE = "credentials.manage"
    API_KEYS_MANAGE = "api_keys.manage"

    # Channel
    CHANNEL_VIEW = "channel.view"
    CHANNEL_MANAGE = "channel.manage"

    # MCP
    MCP_VIEW = "mcp.view"
    MCP_MANAGE = "mcp.manage"

    # Agent
    AGENT_VIEW = "agent.view"
    AGENT_MANAGE = "agent.manage"

    # Audit
    AUDIT_VIEW = "audit.view"
    AUDIT_EXPORT = "audit.export"


# ---------------------------------------------------------------------------
# Role → Permission mapping
# ---------------------------------------------------------------------------

_ALL_PERMISSIONS: frozenset[Permission] = frozenset(Permission)

_ADMIN_ONLY: frozenset[Permission] = frozenset(
    {
        Permission.TEAM_EDIT,
        Permission.TEAM_DELETE,
        Permission.TEAM_INVITE,
        Permission.TEAM_REMOVE_MEMBER,
        Permission.TEAM_CHANGE_ROLE,
        Permission.BILLING_MANAGE,
        Permission.PROJECT_DELETE,
        Permission.CONTAINER_DELETE,
        Permission.DEPLOYMENT_DELETE,
        Permission.API_KEYS_MANAGE,
        Permission.AUDIT_VIEW,
        Permission.AUDIT_EXPORT,
    }
)

# Explicit viewer allowlist. Do NOT auto-derive from ".view" suffix — that
# accidentally grants sensitive read permissions like AUDIT_VIEW. Every
# permission listed here is intentionally safe for read-only role.
_VIEWER_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.TEAM_VIEW,
        Permission.BILLING_VIEW,
        Permission.PROJECT_LIST,
        Permission.PROJECT_VIEW,
        Permission.FILE_READ,
        Permission.CONTAINER_VIEW,
        Permission.CHAT_VIEW,
        Permission.DEPLOYMENT_VIEW,
        Permission.GIT_VIEW,
        Permission.KANBAN_VIEW,
        Permission.SNAPSHOT_VIEW,
        Permission.CREDENTIALS_VIEW,
        Permission.CHANNEL_VIEW,
        Permission.MCP_VIEW,
        Permission.AGENT_VIEW,
    }
)

ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "admin": _ALL_PERMISSIONS,
    "editor": _ALL_PERMISSIONS - _ADMIN_ONLY,
    "viewer": _VIEWER_PERMISSIONS,
}


def has_permission(role: str, permission: Permission) -> bool:
    """Return True if *role* grants *permission*."""
    perms = ROLE_PERMISSIONS.get(role)
    if perms is None:
        return False
    return permission in perms


# ---------------------------------------------------------------------------
# Scope labels for API key scope selector UI
# ---------------------------------------------------------------------------

SCOPE_LABELS: dict[str, dict[str, str]] = {
    # Team-level
    Permission.TEAM_VIEW: {"label": "Team — View", "category": "Team"},
    Permission.TEAM_EDIT: {"label": "Team — Edit settings", "category": "Team"},
    Permission.TEAM_DELETE: {"label": "Team — Delete", "category": "Team"},
    Permission.TEAM_INVITE: {"label": "Team — Invite members", "category": "Team"},
    Permission.TEAM_REMOVE_MEMBER: {"label": "Team — Remove members", "category": "Team"},
    Permission.TEAM_CHANGE_ROLE: {"label": "Team — Change roles", "category": "Team"},
    Permission.BILLING_VIEW: {"label": "Billing — View", "category": "Billing"},
    Permission.BILLING_MANAGE: {"label": "Billing — Manage", "category": "Billing"},
    Permission.BILLING_USAGE: {"label": "Billing — View usage", "category": "Billing"},
    # Project-level
    Permission.PROJECT_LIST: {"label": "Projects — List", "category": "Projects"},
    Permission.PROJECT_CREATE: {"label": "Projects — Create", "category": "Projects"},
    Permission.PROJECT_VIEW: {"label": "Projects — View", "category": "Projects"},
    Permission.PROJECT_EDIT: {"label": "Projects — Edit", "category": "Projects"},
    Permission.PROJECT_DELETE: {"label": "Projects — Delete", "category": "Projects"},
    Permission.PROJECT_SETTINGS: {"label": "Projects — Settings", "category": "Projects"},
    # File
    Permission.FILE_READ: {"label": "Files — Read", "category": "Files"},
    Permission.FILE_WRITE: {"label": "Files — Write", "category": "Files"},
    Permission.FILE_DELETE: {"label": "Files — Delete", "category": "Files"},
    # Container
    Permission.CONTAINER_VIEW: {"label": "Containers — View", "category": "Containers"},
    Permission.CONTAINER_CREATE: {"label": "Containers — Create", "category": "Containers"},
    Permission.CONTAINER_EDIT: {"label": "Containers — Edit", "category": "Containers"},
    Permission.CONTAINER_DELETE: {"label": "Containers — Delete", "category": "Containers"},
    Permission.CONTAINER_START_STOP: {"label": "Containers — Start/Stop", "category": "Containers"},
    # Chat / Agent
    Permission.CHAT_VIEW: {"label": "Chat — View messages", "category": "Chat"},
    Permission.CHAT_SEND: {"label": "Chat — Send messages", "category": "Chat"},
    Permission.CHAT_DELETE: {"label": "Chat — Delete", "category": "Chat"},
    # Deployment
    Permission.DEPLOYMENT_VIEW: {"label": "Deployments — View", "category": "Deployments"},
    Permission.DEPLOYMENT_CREATE: {"label": "Deployments — Create", "category": "Deployments"},
    Permission.DEPLOYMENT_DELETE: {"label": "Deployments — Delete", "category": "Deployments"},
    # Git
    Permission.GIT_VIEW: {"label": "Git — View", "category": "Git"},
    Permission.GIT_WRITE: {"label": "Git — Write", "category": "Git"},
    # Kanban
    Permission.KANBAN_VIEW: {"label": "Kanban — View", "category": "Kanban"},
    Permission.KANBAN_EDIT: {"label": "Kanban — Edit", "category": "Kanban"},
    # Snapshot
    Permission.SNAPSHOT_VIEW: {"label": "Snapshots — View", "category": "Snapshots"},
    Permission.SNAPSHOT_CREATE: {"label": "Snapshots — Create", "category": "Snapshots"},
    Permission.SNAPSHOT_RESTORE: {"label": "Snapshots — Restore", "category": "Snapshots"},
    # Terminal
    Permission.TERMINAL_ACCESS: {"label": "Terminal — Access", "category": "Terminal"},
    # Credentials
    Permission.CREDENTIALS_VIEW: {"label": "Credentials — View", "category": "Credentials"},
    Permission.CREDENTIALS_MANAGE: {"label": "Credentials — Manage", "category": "Credentials"},
    Permission.API_KEYS_MANAGE: {"label": "API Keys — Manage", "category": "Credentials"},
    # Channel
    Permission.CHANNEL_VIEW: {"label": "Channels — View", "category": "Channels"},
    Permission.CHANNEL_MANAGE: {"label": "Channels — Manage", "category": "Channels"},
    # MCP
    Permission.MCP_VIEW: {"label": "MCP — View", "category": "MCP"},
    Permission.MCP_MANAGE: {"label": "MCP — Manage", "category": "MCP"},
    # Agent
    Permission.AGENT_VIEW: {"label": "Agents — View", "category": "Agents"},
    Permission.AGENT_MANAGE: {"label": "Agents — Manage", "category": "Agents"},
    # Audit
    Permission.AUDIT_VIEW: {"label": "Audit Log — View", "category": "Audit"},
    Permission.AUDIT_EXPORT: {"label": "Audit Log — Export", "category": "Audit"},
}


# ---------------------------------------------------------------------------
# Core access-check functions
# ---------------------------------------------------------------------------


async def get_team_membership(
    db: AsyncSession,
    team_id: UUID,
    user_id: UUID,
) -> TeamMembership | None:
    """Return the user's *active* membership row in *team_id*, or ``None``."""
    from .models_team import TeamMembership

    result = await db.execute(
        select(TeamMembership).where(
            and_(
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == user_id,
                TeamMembership.is_active.is_(True),
            )
        )
    )
    return result.scalar_one_or_none()


async def check_team_permission(
    db: AsyncSession,
    team_id: UUID,
    user_id: UUID,
    permission: Permission,
) -> TeamMembership:
    """Verify the user holds *permission* in the given team.

    Returns the ``TeamMembership`` row on success.
    Raises ``HTTPException(403)`` when the check fails.

    Platform superusers (``is_superuser=True``) bypass all checks.
    """
    # --- superuser fast-path ---
    from .models_auth import User

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user and user.is_superuser:
        # Still need a membership object for callers that use it. Fetch if exists,
        # otherwise synthesize a lightweight stand-in is not worth it — just fetch.
        membership = await get_team_membership(db, team_id, user_id)
        if membership is not None:
            return membership
        # Superuser without membership: create a transient object so callers
        # that inspect .role see "admin".
        from .models_team import TeamMembership

        return TeamMembership(
            team_id=team_id,
            user_id=user_id,
            role="admin",
            is_active=True,
        )

    membership = await get_team_membership(db, team_id, user_id)
    if membership is None:
        raise HTTPException(status_code=403, detail="Not a member of this team")

    if not has_permission(membership.role, permission):
        raise HTTPException(
            status_code=403,
            detail=f"Role '{membership.role}' does not have permission '{permission.value}'",
        )

    return membership


async def get_effective_project_role(
    db: AsyncSession,
    project: Project,
    user_id: UUID,
) -> str | None:
    """Resolve the effective role a user holds on a project.

    Dual-scope resolution logic:
    1. Check team membership → team_role.
       a. No team membership → check project_memberships only.
       b. Has team membership →
          - team_role == "admin" → return "admin" (admins see everything).
          - Has project_membership → return project_role (override).
          - No project_membership + visibility == "private" → ``None``.
          - No project_membership + visibility == "team" → return team_role.
    """
    # --- superuser fast-path ---
    from .models_auth import User
    from .models_team import ProjectMembership

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user and user.is_superuser:
        return "admin"

    team_membership: TeamMembership | None = None
    if project.team_id is not None:
        team_membership = await get_team_membership(db, project.team_id, user_id)

    # Fetch project-level override (if any)
    proj_membership_result = await db.execute(
        select(ProjectMembership).where(
            and_(
                ProjectMembership.project_id == project.id,
                ProjectMembership.user_id == user_id,
                ProjectMembership.is_active.is_(True),
            )
        )
    )
    proj_membership: ProjectMembership | None = proj_membership_result.scalar_one_or_none()

    if team_membership is None:
        # (1a) No team membership — project-level membership is the only path
        if proj_membership is not None:
            return proj_membership.role
        # Legacy compat: owner_id still grants admin
        if project.owner_id == user_id:
            return "admin"
        return None

    # (1b) Has team membership
    if team_membership.role == "admin":
        return "admin"

    if proj_membership is not None:
        return proj_membership.role

    visibility = getattr(project, "visibility", "team") or "team"
    if visibility == "private":
        # Legacy compat: owner always has access
        if project.owner_id == user_id:
            return "admin"
        return None

    # visibility == "team" — inherit team role
    return team_membership.role


async def get_project_with_access(
    db: AsyncSession,
    project_slug: str,
    user_id: UUID,
    permission: Permission = Permission.PROJECT_VIEW,
) -> tuple:
    """Fetch a project and verify the caller holds *permission* on it.

    This is the **single replacement** for the 25+ scattered ``owner_id`` checks.

    Returns ``(project, effective_role)`` on success.
    Raises:
        HTTPException(404) — project not found.
        HTTPException(403) — user lacks *permission*.
    """
    from .models import Project

    # --- resolve project by UUID or slug ---
    try:
        project_id = UUID(project_slug)
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
    except ValueError:
        result = await db.execute(select(Project).where(Project.slug == project_slug))
        project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    effective_role = await get_effective_project_role(db, project, user_id)

    if effective_role is None:
        # Don't leak existence — 404 for users with zero access
        raise HTTPException(status_code=404, detail="Project not found")

    if not has_permission(effective_role, permission):
        raise HTTPException(
            status_code=403,
            detail=f"Role '{effective_role}' does not have permission '{permission.value}'",
        )

    return project, effective_role
