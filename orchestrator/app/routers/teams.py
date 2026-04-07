"""
Teams API router — CRUD, membership management, invitations, project members, and audit logs.
"""

import asyncio
import csv
import io
import logging
import secrets as stdlib_secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..database import get_db
from ..models import Project
from ..models_auth import User
from ..models_team import (
    AuditLog,
    ProjectMembership,
    Team,
    TeamInvitation,
    TeamMembership,
)
from ..permissions import (
    Permission,
    check_team_permission,
    get_project_with_access,
    get_team_membership,
)
from ..schemas_team import (
    AuditLogFilter,
    AuditLogRead,
    InvitationRead,
    InviteAcceptResponse,
    InviteDetailRead,
    InviteEmailRequest,
    InviteLinkRequest,
    ProjectMemberAdd,
    ProjectMemberRead,
    ProjectMemberUpdate,
    ProjectVisibilityUpdate,
    TeamCreate,
    TeamList,
    TeamMemberRead,
    TeamMemberUpdate,
    TeamRead,
    TeamUpdate,
)
from ..services.audit_service import log_event
from ..services.email_service import get_email_service
from ..users import current_active_user

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_team(db: AsyncSession, team_slug: str) -> Team:
    """Fetch a team by slug or raise 404."""
    result = await db.execute(select(Team).where(Team.slug == team_slug))
    team = result.scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


async def _resolve_project_in_team(
    db: AsyncSession, team: Team, project_slug: str
) -> Project:
    """Fetch a project that belongs to *team* by slug or raise 404."""
    result = await db.execute(
        select(Project).where(
            and_(Project.team_id == team.id, Project.slug == project_slug)
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _copy_library_to_team(
    db: AsyncSession,
    user_id: UUID,
    source_team_id: UUID,
    target_team_id: UUID,
) -> None:
    """Copy a user's installed library (agents, themes, bases) from one team to another.

    Called during team creation so the new team starts with the same
    marketplace installs as the creator's personal team.
    """
    from ..models import (
        UserLibraryTheme,
        UserPurchasedAgent,
        UserPurchasedBase,
    )

    # -- Agents --
    result = await db.execute(
        select(UserPurchasedAgent).where(
            UserPurchasedAgent.user_id == user_id,
            UserPurchasedAgent.team_id == source_team_id,
            UserPurchasedAgent.is_active.is_(True),
        )
    )
    for agent in result.scalars().all():
        db.add(
            UserPurchasedAgent(
                user_id=user_id,
                team_id=target_team_id,
                agent_id=agent.agent_id,
                purchase_type=agent.purchase_type,
                is_active=True,
                selected_model=agent.selected_model,
            )
        )

    # -- Themes --
    result = await db.execute(
        select(UserLibraryTheme).where(
            UserLibraryTheme.user_id == user_id,
            UserLibraryTheme.team_id == source_team_id,
            UserLibraryTheme.is_active.is_(True),
        )
    )
    for theme in result.scalars().all():
        db.add(
            UserLibraryTheme(
                user_id=user_id,
                team_id=target_team_id,
                theme_id=theme.theme_id,
                purchase_type=theme.purchase_type,
                is_active=True,
            )
        )

    # -- Bases --
    result = await db.execute(
        select(UserPurchasedBase).where(
            UserPurchasedBase.user_id == user_id,
            UserPurchasedBase.team_id == source_team_id,
            UserPurchasedBase.is_active.is_(True),
        )
    )
    for base in result.scalars().all():
        db.add(
            UserPurchasedBase(
                user_id=user_id,
                team_id=target_team_id,
                base_id=base.base_id,
                purchase_type=base.purchase_type,
                is_active=True,
            )
        )

    logger.info(
        "Copied library from team %s to team %s for user %s",
        source_team_id,
        target_team_id,
        user_id,
    )


# ============================================================================
# Team CRUD
# ============================================================================


@router.post("/", response_model=TeamRead, status_code=201)
async def create_team(
    body: TeamCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Create a new team. The caller automatically becomes the admin."""
    # Check slug uniqueness
    existing = await db.execute(select(Team).where(Team.slug == body.slug))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Team slug already taken")

    import uuid as _uuid

    team_id = _uuid.uuid4()
    team = Team(
        id=team_id,
        name=body.name,
        slug=body.slug,
        is_personal=False,
        created_by_id=user.id,
    )
    db.add(team)
    await db.flush()

    membership = TeamMembership(
        team_id=team_id,
        user_id=user.id,
        role="admin",
        is_active=True,
    )
    db.add(membership)

    await log_event(
        db,
        team_id=team.id,
        user_id=user.id,
        action="team.created",
        resource_type="team",
        resource_id=team.id,
        details={"name": team.name, "slug": team.slug},
        request=request,
    )

    # Copy the creator's installed library from their personal team to the new team.
    personal_team_id = user.default_team_id
    if personal_team_id:
        await _copy_library_to_team(db, user.id, personal_team_id, team_id)

    await db.commit()
    await db.refresh(team)
    return team


@router.get("/", response_model=list[TeamList])
async def list_teams(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """List all teams the current user is an active member of."""
    result = await db.execute(
        select(Team, TeamMembership.role)
        .join(TeamMembership, TeamMembership.team_id == Team.id)
        .where(
            and_(
                TeamMembership.user_id == user.id,
                TeamMembership.is_active.is_(True),
            )
        )
        .order_by(Team.created_at)
    )
    rows = result.all()
    out: list[TeamList] = []
    for team, role in rows:
        item = TeamList.model_validate(team)
        item.role = role
        # Only show "Personal" badge to the team's owner
        if item.is_personal and team.created_by_id != user.id:
            item.is_personal = False
        out.append(item)
    return out


# ── Invitation public routes (must be before /{team_slug} to avoid collision) ──


@router.get("/invitations/{token}", response_model=InviteDetailRead)
async def get_invite_details(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint — get invite details for the accept page. No auth required."""
    result = await db.execute(
        select(TeamInvitation)
        .options(selectinload(TeamInvitation.team))
        .where(TeamInvitation.token == token)
    )
    invitation = result.scalar_one_or_none()
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found")

    team = invitation.team
    now = datetime.now(UTC)
    is_valid = (
        invitation.revoked_at is None
        and invitation.expires_at > now
        and (invitation.max_uses is None or invitation.use_count < invitation.max_uses)
    )

    return InviteDetailRead(
        team_name=team.name,
        team_slug=team.slug,
        team_avatar_url=team.avatar_url,
        role=invitation.role,
        invite_type=invitation.invite_type,
        expires_at=invitation.expires_at,
        is_valid=is_valid,
    )


@router.post("/invitations/{token}/accept", response_model=InviteAcceptResponse)
async def accept_invitation(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Accept an invitation. Any authenticated user."""
    result = await db.execute(
        select(TeamInvitation)
        .options(selectinload(TeamInvitation.team))
        .where(TeamInvitation.token == token)
    )
    invitation = result.scalar_one_or_none()
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found")

    # Validate
    if invitation.revoked_at is not None:
        raise HTTPException(status_code=410, detail="Invitation has been revoked")
    if invitation.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=410, detail="Invitation has expired")
    if invitation.max_uses is not None and invitation.use_count >= invitation.max_uses:
        raise HTTPException(status_code=410, detail="Invitation has reached maximum uses")

    # Check not already an active member
    existing = await get_team_membership(db, invitation.team_id, user.id)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Already a member of this team")

    # Check for inactive membership (user previously left) — reactivate instead of inserting
    inactive_result = await db.execute(
        select(TeamMembership).where(
            and_(
                TeamMembership.team_id == invitation.team_id,
                TeamMembership.user_id == user.id,
                TeamMembership.is_active.is_(False),
            )
        )
    )
    inactive = inactive_result.scalar_one_or_none()

    if inactive:
        # Reactivate existing membership with the new role
        inactive.is_active = True
        inactive.role = invitation.role
        inactive.invited_by_id = invitation.invited_by_id
        membership = inactive
    else:
        # Create new membership
        membership = TeamMembership(
            team_id=invitation.team_id,
            user_id=user.id,
            role=invitation.role,
            is_active=True,
            invited_by_id=invitation.invited_by_id,
        )
        db.add(membership)

    # Update invitation tracking
    invitation.use_count += 1
    if invitation.invite_type == "email":
        invitation.accepted_at = datetime.now(UTC)
        invitation.accepted_by_id = user.id

    await log_event(
        db,
        team_id=invitation.team_id,
        user_id=user.id,
        action="member.joined",
        resource_type="membership",
        resource_id=membership.id,
        details={"role": invitation.role, "invite_type": invitation.invite_type},
        request=request,
    )
    await db.commit()

    team = invitation.team
    return InviteAcceptResponse(
        team_id=team.id,
        team_name=team.name,
        team_slug=team.slug,
        role=invitation.role,
    )


@router.get("/{team_slug}", response_model=TeamRead)
async def get_team(
    team_slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Get team details. Requires active membership."""
    team = await _resolve_team(db, team_slug)
    await check_team_permission(db, team.id, user.id, Permission.TEAM_VIEW)
    return team


@router.patch("/{team_slug}", response_model=TeamRead)
async def update_team(
    team_slug: str,
    body: TeamUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Update team name/slug/avatar. Admin only."""
    team = await _resolve_team(db, team_slug)
    await check_team_permission(db, team.id, user.id, Permission.TEAM_EDIT)

    provided = body.model_dump(exclude_unset=True)
    changes: dict = {}
    if "name" in provided and provided["name"] is not None:
        changes["name"] = provided["name"]
        team.name = provided["name"]
    if "slug" in provided and provided["slug"] is not None and provided["slug"] != team.slug:
        dup = await db.execute(select(Team).where(Team.slug == provided["slug"]))
        if dup.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="Team slug already taken")
        changes["slug"] = provided["slug"]
        team.slug = provided["slug"]
    if "avatar_url" in provided:
        changes["avatar_url"] = provided["avatar_url"]
        team.avatar_url = provided["avatar_url"]

    if changes:
        await log_event(
            db,
            team_id=team.id,
            user_id=user.id,
            action="team.updated",
            resource_type="team",
            resource_id=team.id,
            details=changes,
            request=request,
        )
        await db.commit()
        await db.refresh(team)
    return team


@router.delete("/{team_slug}", status_code=204)
async def delete_team(
    team_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Delete team. Admin only. Cannot delete personal teams."""
    team = await _resolve_team(db, team_slug)
    await check_team_permission(db, team.id, user.id, Permission.TEAM_DELETE)

    if team.is_personal:
        raise HTTPException(status_code=400, detail="Cannot delete a personal team")

    await log_event(
        db,
        team_id=team.id,
        user_id=user.id,
        action="team.deleted",
        resource_type="team",
        resource_id=team.id,
        details={"name": team.name, "slug": team.slug},
        request=request,
    )
    # Delete memberships, invitations, and audit logs explicitly to avoid
    # SQLAlchemy trying to SET NULL on non-nullable FK columns before DB cascade
    from sqlalchemy import delete as sa_delete

    await db.execute(sa_delete(TeamMembership).where(TeamMembership.team_id == team.id))
    await db.execute(sa_delete(TeamInvitation).where(TeamInvitation.team_id == team.id))
    await db.execute(sa_delete(AuditLog).where(AuditLog.team_id == team.id))
    await db.delete(team)
    await db.commit()


@router.post("/{team_slug}/switch", status_code=200)
async def switch_team(
    team_slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Set team as user's default_team_id."""
    team = await _resolve_team(db, team_slug)
    # Must be an active member
    membership = await get_team_membership(db, team.id, user.id)
    if membership is None:
        raise HTTPException(status_code=403, detail="Not a member of this team")

    user.default_team_id = team.id
    await db.commit()
    return {"default_team_id": str(team.id)}


# ============================================================================
# Member Management
# ============================================================================


@router.get("/{team_slug}/members", response_model=list[TeamMemberRead])
async def list_members(
    team_slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """List team members. Any active member can view."""
    team = await _resolve_team(db, team_slug)
    await check_team_permission(db, team.id, user.id, Permission.TEAM_VIEW)

    result = await db.execute(
        select(TeamMembership)
        .options(selectinload(TeamMembership.user))
        .where(
            and_(
                TeamMembership.team_id == team.id,
                TeamMembership.is_active.is_(True),
            )
        )
        .order_by(TeamMembership.joined_at)
    )
    members = result.scalars().all()

    out: list[TeamMemberRead] = []
    for m in members:
        item = TeamMemberRead(
            id=m.id,
            user_id=m.user_id,
            role=m.role,
            is_active=m.is_active,
            joined_at=m.joined_at,
            user_name=m.user.name if m.user else None,
            user_email=m.user.email if m.user else None,
            user_avatar_url=getattr(m.user, "avatar_url", None) if m.user else None,
        )
        out.append(item)
    return out


@router.post("/{team_slug}/members/invite", response_model=InvitationRead, status_code=201)
async def invite_by_email(
    team_slug: str,
    body: InviteEmailRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Send email invitation. Admin only."""
    team = await _resolve_team(db, team_slug)
    await check_team_permission(db, team.id, user.id, Permission.TEAM_INVITE)

    # Check for existing active member with this email
    existing_user = await db.execute(select(User).where(User.email == body.email))
    existing_user_obj = existing_user.scalar_one_or_none()
    if existing_user_obj:
        existing_membership = await get_team_membership(db, team.id, existing_user_obj.id)
        if existing_membership is not None:
            raise HTTPException(status_code=409, detail="User is already a member of this team")

    # Check for duplicate pending invitation
    pending = await db.execute(
        select(TeamInvitation).where(
            and_(
                TeamInvitation.team_id == team.id,
                TeamInvitation.email == body.email,
                TeamInvitation.invite_type == "email",
                TeamInvitation.accepted_at.is_(None),
                TeamInvitation.revoked_at.is_(None),
                TeamInvitation.expires_at > datetime.now(UTC),
            )
        )
    )
    if pending.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="A pending invitation already exists for this email")

    # Rate limit: 50 invitations per day
    day_ago = datetime.now(UTC) - timedelta(days=1)
    count_result = await db.execute(
        select(func.count()).where(
            and_(
                TeamInvitation.team_id == team.id,
                TeamInvitation.invited_by_id == user.id,
                TeamInvitation.created_at > day_ago,
            )
        )
    )
    if count_result.scalar() >= 50:
        raise HTTPException(status_code=429, detail="Invitation rate limit exceeded (50/day)")

    token = stdlib_secrets.token_urlsafe(32)
    invitation = TeamInvitation(
        team_id=team.id,
        email=body.email,
        role=body.role,
        token=token,
        invite_type="email",
        invited_by_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(invitation)

    await log_event(
        db,
        team_id=team.id,
        user_id=user.id,
        action="member.invited",
        resource_type="invitation",
        resource_id=invitation.id,
        details={"email": body.email, "role": body.role, "invite_type": "email"},
        request=request,
    )
    await db.commit()
    await db.refresh(invitation)

    # Send invitation email (non-blocking)
    base_url = get_settings().get_app_base_url
    invite_url = f"{base_url}/invite/{invitation.token}"
    logger.info(f"Invite created: id={invitation.id} token={invitation.token} url={invite_url}")
    inviter_name = user.name or user.email or "A team member"
    email_svc = get_email_service()
    asyncio.create_task(
        email_svc.send_team_invite(body.email, invite_url, team.name, inviter_name, body.role)
    )

    return invitation


@router.post("/{team_slug}/members/link", response_model=InvitationRead, status_code=201)
async def create_invite_link(
    team_slug: str,
    body: InviteLinkRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Create an invite link. Admin only. Max 10 active links per team."""
    team = await _resolve_team(db, team_slug)
    await check_team_permission(db, team.id, user.id, Permission.TEAM_INVITE)

    # Max 10 active links
    active_links = await db.execute(
        select(func.count()).where(
            and_(
                TeamInvitation.team_id == team.id,
                TeamInvitation.invite_type == "link",
                TeamInvitation.revoked_at.is_(None),
                TeamInvitation.expires_at > datetime.now(UTC),
            )
        )
    )
    if active_links.scalar() >= 10:
        raise HTTPException(status_code=400, detail="Maximum active invite links (10) reached")

    token = stdlib_secrets.token_urlsafe(32)
    invitation = TeamInvitation(
        team_id=team.id,
        email="",  # link invites have no specific email
        role=body.role,
        token=token,
        invite_type="link",
        invited_by_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=body.expires_in_days),
        max_uses=body.max_uses,
    )
    db.add(invitation)

    await log_event(
        db,
        team_id=team.id,
        user_id=user.id,
        action="member.invited",
        resource_type="invitation",
        resource_id=invitation.id,
        details={
            "role": body.role,
            "invite_type": "link",
            "max_uses": body.max_uses,
            "expires_in_days": body.expires_in_days,
        },
        request=request,
    )
    await db.commit()
    await db.refresh(invitation)
    return invitation


@router.delete("/{team_slug}/members/{user_id}", status_code=204)
async def remove_member(
    team_slug: str,
    user_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Remove member. Admin only. Deactivates team + project memberships."""
    team = await _resolve_team(db, team_slug)
    await check_team_permission(db, team.id, user.id, Permission.TEAM_REMOVE_MEMBER)

    target_membership = await get_team_membership(db, team.id, user_id)
    if target_membership is None:
        raise HTTPException(status_code=404, detail="Member not found")

    target_membership.is_active = False

    # Deactivate all project memberships for this user in this team's projects
    team_projects = await db.execute(
        select(Project.id).where(Project.team_id == team.id)
    )
    project_ids = [row[0] for row in team_projects.all()]
    if project_ids:
        proj_memberships = await db.execute(
            select(ProjectMembership).where(
                and_(
                    ProjectMembership.user_id == user_id,
                    ProjectMembership.project_id.in_(project_ids),
                    ProjectMembership.is_active.is_(True),
                )
            )
        )
        for pm in proj_memberships.scalars().all():
            pm.is_active = False

    await log_event(
        db,
        team_id=team.id,
        user_id=user.id,
        action="member.removed",
        resource_type="membership",
        resource_id=target_membership.id,
        details={"removed_user_id": str(user_id)},
        request=request,
    )
    await db.commit()


@router.patch("/{team_slug}/members/{user_id}", response_model=TeamMemberRead)
async def change_member_role(
    team_slug: str,
    user_id: UUID,
    body: TeamMemberUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Change a member's role. Admin only. Cannot change own role."""
    team = await _resolve_team(db, team_slug)
    await check_team_permission(db, team.id, user.id, Permission.TEAM_CHANGE_ROLE)

    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot change your own role")

    target_membership = await get_team_membership(db, team.id, user_id)
    if target_membership is None:
        raise HTTPException(status_code=404, detail="Member not found")

    old_role = target_membership.role
    target_membership.role = body.role

    await log_event(
        db,
        team_id=team.id,
        user_id=user.id,
        action="member.role_changed",
        resource_type="membership",
        resource_id=target_membership.id,
        details={
            "target_user_id": str(user_id),
            "old_role": old_role,
            "new_role": body.role,
        },
        request=request,
    )
    await db.commit()
    await db.refresh(target_membership)

    # Re-fetch with user join
    result = await db.execute(
        select(TeamMembership)
        .options(selectinload(TeamMembership.user))
        .where(TeamMembership.id == target_membership.id)
    )
    m = result.scalar_one()
    return TeamMemberRead(
        id=m.id,
        user_id=m.user_id,
        role=m.role,
        is_active=m.is_active,
        joined_at=m.joined_at,
        user_name=m.user.name if m.user else None,
        user_email=m.user.email if m.user else None,
        user_avatar_url=getattr(m.user, "avatar_url", None) if m.user else None,
    )


@router.post("/{team_slug}/leave", status_code=200)
async def leave_team(
    team_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Leave team. Blocks if sole admin or personal team."""
    team = await _resolve_team(db, team_slug)

    if team.is_personal and team.created_by_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot leave your personal team")

    membership = await get_team_membership(db, team.id, user.id)
    if membership is None:
        raise HTTPException(status_code=403, detail="Not a member of this team")

    if membership.role == "admin":
        admin_count = await db.execute(
            select(func.count()).where(
                and_(
                    TeamMembership.team_id == team.id,
                    TeamMembership.role == "admin",
                    TeamMembership.is_active.is_(True),
                )
            )
        )
        if admin_count.scalar() <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot leave: you are the sole admin. Transfer admin role first.",
            )

    membership.is_active = False

    await log_event(
        db,
        team_id=team.id,
        user_id=user.id,
        action="member.left",
        resource_type="membership",
        resource_id=membership.id,
        request=request,
    )
    await db.commit()
    return {"detail": "Left team successfully"}


# ============================================================================
# Invitations
# ============================================================================


@router.get("/{team_slug}/invitations", response_model=list[InvitationRead])
async def list_invitations(
    team_slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """List pending invitations. Admin only."""
    team = await _resolve_team(db, team_slug)
    await check_team_permission(db, team.id, user.id, Permission.TEAM_INVITE)

    result = await db.execute(
        select(TeamInvitation)
        .where(
            and_(
                TeamInvitation.team_id == team.id,
                TeamInvitation.accepted_at.is_(None),
                TeamInvitation.revoked_at.is_(None),
                TeamInvitation.expires_at > datetime.now(UTC),
            )
        )
        .order_by(TeamInvitation.created_at.desc())
    )
    return result.scalars().all()


@router.delete("/{team_slug}/invitations/{invitation_id}", status_code=204)
async def revoke_invitation(
    team_slug: str,
    invitation_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Revoke an invitation. Admin only."""
    team = await _resolve_team(db, team_slug)
    await check_team_permission(db, team.id, user.id, Permission.TEAM_INVITE)

    result = await db.execute(
        select(TeamInvitation).where(
            and_(
                TeamInvitation.id == invitation_id,
                TeamInvitation.team_id == team.id,
            )
        )
    )
    invitation = result.scalar_one_or_none()
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found")

    invitation.revoked_at = datetime.now(UTC)

    await log_event(
        db,
        team_id=team.id,
        user_id=user.id,
        action="invitation.revoked",
        resource_type="invitation",
        resource_id=invitation.id,
        details={"email": invitation.email, "invite_type": invitation.invite_type},
        request=request,
    )
    await db.commit()



# (invite accept/details routes moved before /{team_slug} to avoid route collision)


# ============================================================================
# Project Members
# ============================================================================


@router.get(
    "/{team_slug}/projects/{project_slug}/members",
    response_model=list[ProjectMemberRead],
)
async def list_project_members(
    team_slug: str,
    project_slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """List project members with user info."""
    team = await _resolve_team(db, team_slug)
    await check_team_permission(db, team.id, user.id, Permission.TEAM_VIEW)
    project = await _resolve_project_in_team(db, team, project_slug)

    result = await db.execute(
        select(ProjectMembership)
        .options(selectinload(ProjectMembership.user))
        .where(
            and_(
                ProjectMembership.project_id == project.id,
                ProjectMembership.is_active.is_(True),
            )
        )
        .order_by(ProjectMembership.created_at)
    )
    members = result.scalars().all()

    return [
        ProjectMemberRead(
            id=m.id,
            user_id=m.user_id,
            role=m.role,
            is_active=m.is_active,
            created_at=m.created_at,
            user_name=m.user.name if m.user else None,
            user_email=m.user.email if m.user else None,
        )
        for m in members
    ]


@router.post(
    "/{team_slug}/projects/{project_slug}/members",
    response_model=ProjectMemberRead,
    status_code=201,
)
async def add_project_member(
    team_slug: str,
    project_slug: str,
    body: ProjectMemberAdd,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Add a project member. Project admin only."""
    team = await _resolve_team(db, team_slug)
    project = await _resolve_project_in_team(db, team, project_slug)

    # Caller must be project admin
    _, caller_role = await get_project_with_access(
        db, project_slug, user.id, Permission.PROJECT_SETTINGS
    )

    # Target must be a team member
    target_team_membership = await get_team_membership(db, team.id, body.user_id)
    if target_team_membership is None:
        raise HTTPException(status_code=400, detail="User is not a member of this team")

    # Check not already a project member
    existing = await db.execute(
        select(ProjectMembership).where(
            and_(
                ProjectMembership.project_id == project.id,
                ProjectMembership.user_id == body.user_id,
            )
        )
    )
    existing_pm = existing.scalar_one_or_none()
    if existing_pm is not None:
        if existing_pm.is_active:
            raise HTTPException(status_code=409, detail="User is already a project member")
        # Reactivate
        existing_pm.is_active = True
        existing_pm.role = body.role
        existing_pm.granted_by_id = user.id
        await db.commit()
        await db.refresh(existing_pm)
        return ProjectMemberRead(
            id=existing_pm.id,
            user_id=existing_pm.user_id,
            role=existing_pm.role,
            is_active=existing_pm.is_active,
            created_at=existing_pm.created_at,
        )

    pm = ProjectMembership(
        project_id=project.id,
        user_id=body.user_id,
        role=body.role,
        granted_by_id=user.id,
        is_active=True,
    )
    db.add(pm)

    await log_event(
        db,
        team_id=team.id,
        user_id=user.id,
        action="project.member_added",
        resource_type="project_membership",
        resource_id=pm.id,
        project_id=project.id,
        details={"target_user_id": str(body.user_id), "role": body.role},
        request=request,
    )
    await db.commit()
    await db.refresh(pm)
    return ProjectMemberRead(
        id=pm.id,
        user_id=pm.user_id,
        role=pm.role,
        is_active=pm.is_active,
        created_at=pm.created_at,
    )


@router.patch(
    "/{team_slug}/projects/{project_slug}/members/{user_id}",
    response_model=ProjectMemberRead,
)
async def change_project_member_role(
    team_slug: str,
    project_slug: str,
    user_id: UUID,
    body: ProjectMemberUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Change a project member's role. Project admin only."""
    team = await _resolve_team(db, team_slug)
    project = await _resolve_project_in_team(db, team, project_slug)

    await get_project_with_access(db, project_slug, user.id, Permission.PROJECT_SETTINGS)

    result = await db.execute(
        select(ProjectMembership).where(
            and_(
                ProjectMembership.project_id == project.id,
                ProjectMembership.user_id == user_id,
                ProjectMembership.is_active.is_(True),
            )
        )
    )
    pm = result.scalar_one_or_none()
    if pm is None:
        raise HTTPException(status_code=404, detail="Project member not found")

    old_role = pm.role
    pm.role = body.role

    await log_event(
        db,
        team_id=team.id,
        user_id=user.id,
        action="project.member_role_changed",
        resource_type="project_membership",
        resource_id=pm.id,
        project_id=project.id,
        details={
            "target_user_id": str(user_id),
            "old_role": old_role,
            "new_role": body.role,
        },
        request=request,
    )
    await db.commit()
    await db.refresh(pm)
    return ProjectMemberRead(
        id=pm.id,
        user_id=pm.user_id,
        role=pm.role,
        is_active=pm.is_active,
        created_at=pm.created_at,
    )


@router.delete("/{team_slug}/projects/{project_slug}/members/{user_id}", status_code=204)
async def remove_project_member(
    team_slug: str,
    project_slug: str,
    user_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Remove a project member. Project admin only."""
    team = await _resolve_team(db, team_slug)
    project = await _resolve_project_in_team(db, team, project_slug)

    await get_project_with_access(db, project_slug, user.id, Permission.PROJECT_SETTINGS)

    result = await db.execute(
        select(ProjectMembership).where(
            and_(
                ProjectMembership.project_id == project.id,
                ProjectMembership.user_id == user_id,
                ProjectMembership.is_active.is_(True),
            )
        )
    )
    pm = result.scalar_one_or_none()
    if pm is None:
        raise HTTPException(status_code=404, detail="Project member not found")

    pm.is_active = False

    await log_event(
        db,
        team_id=team.id,
        user_id=user.id,
        action="project.member_removed",
        resource_type="project_membership",
        resource_id=pm.id,
        project_id=project.id,
        details={"removed_user_id": str(user_id)},
        request=request,
    )
    await db.commit()


@router.patch("/{team_slug}/projects/{project_slug}/visibility")
async def update_project_visibility(
    team_slug: str,
    project_slug: str,
    body: ProjectVisibilityUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Update project visibility. Admin only."""
    team = await _resolve_team(db, team_slug)
    project = await _resolve_project_in_team(db, team, project_slug)
    await check_team_permission(db, team.id, user.id, Permission.PROJECT_SETTINGS)

    old_visibility = project.visibility
    project.visibility = body.visibility

    await log_event(
        db,
        team_id=team.id,
        user_id=user.id,
        action="project.visibility_changed",
        resource_type="project",
        resource_id=project.id,
        project_id=project.id,
        details={"old_visibility": old_visibility, "new_visibility": body.visibility},
        request=request,
    )
    await db.commit()
    return {"visibility": project.visibility}


# ============================================================================
# Audit Log
# ============================================================================


def _build_audit_query(
    team_id: UUID,
    *,
    project_id: UUID | None = None,
    action: str | None = None,
    user_id: UUID | None = None,
    resource_type: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
):
    """Build a filtered audit log query."""
    conditions = [AuditLog.team_id == team_id]
    if project_id is not None:
        conditions.append(AuditLog.project_id == project_id)
    if action is not None:
        conditions.append(AuditLog.action == action)
    if user_id is not None:
        conditions.append(AuditLog.user_id == user_id)
    if resource_type is not None:
        conditions.append(AuditLog.resource_type == resource_type)
    if from_date is not None:
        conditions.append(AuditLog.created_at >= from_date)
    if to_date is not None:
        conditions.append(AuditLog.created_at <= to_date)
    return select(AuditLog).where(and_(*conditions)).order_by(AuditLog.created_at.desc())


@router.get("/{team_slug}/audit-log", response_model=list[AuditLogRead])
async def get_audit_log(
    team_slug: str,
    action: str | None = Query(None),
    user_id: UUID | None = Query(None),
    project_id: UUID | None = Query(None),
    resource_type: str | None = Query(None),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Team audit log with filtering. Admin only."""
    team = await _resolve_team(db, team_slug)
    await check_team_permission(db, team.id, user.id, Permission.AUDIT_VIEW)

    query = _build_audit_query(
        team.id,
        action=action,
        user_id=user_id,
        project_id=project_id,
        resource_type=resource_type,
        from_date=from_date,
        to_date=to_date,
    )
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(
        query.options(
            selectinload(AuditLog.project),
            selectinload(AuditLog.user),
        )
    )
    entries = result.scalars().all()
    return [
        AuditLogRead(
            id=e.id,
            team_id=e.team_id,
            project_id=e.project_id,
            project_name=e.project.name if e.project else None,
            user_id=e.user_id,
            user_name=e.user.name if e.user else None,
            action=e.action,
            resource_type=e.resource_type,
            resource_id=e.resource_id,
            details=e.details,
            ip_address=e.ip_address,
            created_at=e.created_at,
        )
        for e in entries
    ]


@router.get(
    "/{team_slug}/projects/{project_slug}/audit-log",
    response_model=list[AuditLogRead],
)
async def get_project_audit_log(
    team_slug: str,
    project_slug: str,
    action: str | None = Query(None),
    user_id: UUID | None = Query(None),
    resource_type: str | None = Query(None),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Project-scoped audit log. Any member can view."""
    team = await _resolve_team(db, team_slug)
    await check_team_permission(db, team.id, user.id, Permission.TEAM_VIEW)
    project = await _resolve_project_in_team(db, team, project_slug)

    query = _build_audit_query(
        team.id,
        project_id=project.id,
        action=action,
        user_id=user_id,
        resource_type=resource_type,
        from_date=from_date,
        to_date=to_date,
    )
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/{team_slug}/audit-log/export", status_code=200)
async def export_audit_log(
    team_slug: str,
    body: AuditLogFilter,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Export audit log as CSV. Admin only."""
    team = await _resolve_team(db, team_slug)
    await check_team_permission(db, team.id, user.id, Permission.AUDIT_EXPORT)

    query = _build_audit_query(
        team.id,
        action=body.action,
        user_id=body.user_id,
        project_id=body.project_id,
        resource_type=body.resource_type,
        from_date=body.from_date,
        to_date=body.to_date,
    )
    # Cap export to 10k rows to avoid memory issues
    query = query.limit(10000)
    result = await db.execute(query)
    rows = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "team_id", "project_id", "user_id", "action",
        "resource_type", "resource_id", "details", "ip_address", "created_at",
    ])
    for row in rows:
        writer.writerow([
            str(row.id),
            str(row.team_id),
            str(row.project_id) if row.project_id else "",
            str(row.user_id),
            row.action,
            row.resource_type,
            str(row.resource_id) if row.resource_id else "",
            str(row.details) if row.details else "",
            row.ip_address or "",
            row.created_at.isoformat() if row.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=audit-log-{team.slug}.csv"},
    )
