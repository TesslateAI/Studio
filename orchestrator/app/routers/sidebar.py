"""
Sidebar API — hierarchical tree of projects (folders) + their chats plus
root-level chats that aren't attached to any project.

Single endpoint ``GET /api/sidebar/tree`` powers the left-nav. Returns the
top-N recent projects (each with its top-N recent chats) and the top-N
recent root-level chats. For larger listings inside a specific project,
the frontend falls back to ``GET /api/chat/{project_id}/sessions``.

Project visibility mirrors ``/api/projects/`` — team-membership aware, with
admins seeing all team projects and regular users seeing team-visible ones
plus projects they have explicit membership in. App-instance projects are
hidden (they appear under Library → Apps).
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_, select
from sqlalchemy import func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Chat, Project, User
from ..models_team import ProjectMembership, TeamMembership
from ..services.apps.project_scopes import exclude_app_instances_clause
from ..users import current_active_user

router = APIRouter(prefix="/api/sidebar", tags=["sidebar"])
logger = logging.getLogger(__name__)

# Chat statuses to hide from the sidebar — archived/deleted shouldn't clutter
# the nav. They're still fetchable via the per-session endpoints.
HIDDEN_CHAT_STATUSES = ("archived", "deleted")


def _chat_team_filter(user: User):
    """Restrict chats to the user's active team (or legacy team-less rows)."""
    if user.default_team_id:
        return or_(
            Chat.team_id == user.default_team_id,
            Chat.team_id.is_(None),
        )
    return True  # bare True = no-op in where-list


async def _visible_projects_query(user: User, db: AsyncSession):
    """Build a SELECT that yields only the projects this user should see in
    the sidebar, matching ``/api/projects/`` semantics."""
    team_id = user.default_team_id
    if not team_id:
        return None  # signals caller to skip the projects fetch entirely

    membership = await db.execute(
        select(TeamMembership).where(
            and_(
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == user.id,
                TeamMembership.is_active.is_(True),
            )
        )
    )
    member = membership.scalar_one_or_none()
    is_superuser = getattr(user, "is_superuser", False)
    if not member and not is_superuser:
        return None

    project_kind_filter = exclude_app_instances_clause()
    base = select(Project).where(and_(Project.team_id == team_id, project_kind_filter))
    if (member and member.role == "admin") or is_superuser:
        return base
    # Regular member: team-visible OR explicit per-project membership
    return base.where(
        or_(
            Project.visibility == "team",
            Project.id.in_(
                select(ProjectMembership.project_id).where(
                    and_(
                        ProjectMembership.user_id == user.id,
                        ProjectMembership.is_active.is_(True),
                    )
                )
            ),
        )
    )


def _serialize_chat(chat: Chat) -> dict:
    return {
        "id": str(chat.id),
        "title": chat.title or "Untitled",
        "status": chat.status or "active",
        "origin": chat.origin or "browser",
        "project_id": str(chat.project_id) if chat.project_id else None,
        "created_at": chat.created_at.isoformat() if chat.created_at else None,
        "updated_at": chat.updated_at.isoformat() if chat.updated_at else None,
    }


@router.get("/tree")
async def sidebar_tree(
    project_limit: int = Query(30, ge=1, le=100),
    root_chat_limit: int = Query(50, ge=1, le=200),
    chats_per_project: int = Query(20, ge=1, le=100),
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the sidebar hierarchy in a single round-trip.

    Response::

        {
          "rootChats":  [{...chat...}, ...],
          "projects":   [{id, name, slug, updated_at, chats: [{...}, ...]}, ...]
        }
    """
    # --- Projects: rank by the latest activity inside them ---
    # Fetch each visible project with its most-recent chat-updated-at, then
    # sort in Python by max(project.updated_at, max_chat_updated_at). Sorting
    # client-side keeps us portable between Postgres (cloud) and SQLite
    # (desktop) — SQLite has no GREATEST(). Project count is bounded by the
    # team's project volume and further capped by project_limit below, so
    # the in-memory sort is fine.
    visible_projects = await _visible_projects_query(current_user, db)
    if visible_projects is None:
        # User has no active team or no team membership → no projects to show,
        # but root chats (team-less, user-owned) may still exist.
        project_records: list = []
    else:
        visible_subq = visible_projects.subquery()
        project_rows = await db.execute(
            select(Project, sa_func.max(Chat.updated_at).label("max_chat_updated_at"))
            .join(visible_subq, Project.id == visible_subq.c.id)
            .outerjoin(
                Chat,
                and_(
                    Chat.project_id == Project.id,
                    Chat.status.notin_(HIDDEN_CHAT_STATUSES),
                ),
            )
            .group_by(Project.id)
        )
        project_records_all = project_rows.all()

        project_records = sorted(
            project_records_all,
            key=lambda row: max(
                filter(
                    None,
                    (row[0].updated_at, row[1], row[0].created_at),
                ),
                default=row[0].created_at,
            ),
            reverse=True,
        )[:project_limit]

    projects: list[dict] = []
    project_ids: list[UUID] = []
    project_map: dict[UUID, dict] = {}
    for project, max_chat_updated_at in project_records:
        latest_activity = max(
            filter(None, (project.updated_at, max_chat_updated_at)),
            default=project.created_at,
        )
        entry = {
            "id": str(project.id),
            "name": project.name,
            "slug": project.slug,
            "description": project.description,
            "visibility": project.visibility,
            "runtime": project.runtime,
            "created_at": project.created_at.isoformat() if project.created_at else None,
            "updated_at": project.updated_at.isoformat() if project.updated_at else None,
            "latest_activity_at": latest_activity.isoformat() if latest_activity else None,
            "chats": [],
        }
        projects.append(entry)
        project_ids.append(project.id)
        project_map[project.id] = entry

    # --- Chats inside the returned projects (single batched query) ---
    if project_ids:
        ranked = select(
            Chat,
            sa_func.row_number()
            .over(
                partition_by=Chat.project_id,
                order_by=(
                    Chat.updated_at.desc().nullslast(),
                    Chat.created_at.desc(),
                ),
            )
            .label("rn"),
        ).where(
            Chat.user_id == current_user.id,
            Chat.project_id.in_(project_ids),
            Chat.status.notin_(HIDDEN_CHAT_STATUSES),
        )
        ranked_sub = ranked.subquery()
        chat_rows = await db.execute(
            select(Chat)
            .join(ranked_sub, Chat.id == ranked_sub.c.id)
            .where(ranked_sub.c.rn <= chats_per_project)
            .order_by(Chat.updated_at.desc().nullslast(), Chat.created_at.desc())
        )
        for chat in chat_rows.scalars().all():
            entry = project_map.get(chat.project_id)
            if entry is not None:
                entry["chats"].append(_serialize_chat(chat))

    # --- Root chats (no project) ---
    root_chat_rows = await db.execute(
        select(Chat)
        .where(
            Chat.user_id == current_user.id,
            Chat.project_id.is_(None),
            Chat.status.notin_(HIDDEN_CHAT_STATUSES),
            _chat_team_filter(current_user),
        )
        .order_by(Chat.updated_at.desc().nullslast(), Chat.created_at.desc())
        .limit(root_chat_limit)
    )
    root_chats = [_serialize_chat(c) for c in root_chat_rows.scalars().all()]

    return {"rootChats": root_chats, "projects": projects}
