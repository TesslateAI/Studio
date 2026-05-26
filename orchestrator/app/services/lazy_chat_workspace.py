"""Per-user default chat workspace — lazy-created on first chat.

Every chat (browser, API, gateway) must have a Project attached so that
agent tools needing project context — file I/O, bash, container control,
kanban, schedule, credential storage — always have a valid scope. A chat
with ``project_id IS NULL`` works for plain text Q&A but fails the moment
the agent calls any project-scoped tool, often with cryptic
"cannot resolve project path" errors from deep in the orchestrator.

To make those tool calls always-succeed without forcing the user to
pre-create a project, we lazily mint a single per-user workspace the
first time the user starts a project-less chat. It is:

- One row per user, ``name='~workspace~'``, ``project_kind='workspace'``,
  ``compute_tier='none'`` (no containers, no startup cost).
- Tied to the user's personal team so RBAC checks pass uniformly.
- Reusable as the home for CLI tool installations, credentials, and any
  runtime state the agent accumulates across sessions.

Sibling to ``services.automations.lazy_workspace`` (`~automations~`).
They are intentionally distinct: the automation workspace is the spend /
artifact home for scheduled tasks; this one is the general-purpose
default for ad-hoc chats. Keeping them separate avoids cross-feature
surprise when a user uses one but not the other.
"""

from __future__ import annotations

import logging
import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PROJECT_KIND_WORKSPACE, Project
from ..models_team import ProjectMembership, Team

logger = logging.getLogger(__name__)


_WORKSPACE_NAME = "~workspace~"


__all__ = [
    "ensure_user_default_workspace",
]


async def _get_personal_team_id(db: AsyncSession, user_id: UUID) -> UUID | None:
    result = await db.execute(
        select(Team.id)
        .where(Team.created_by_id == user_id)
        .where(Team.is_personal.is_(True))
        .limit(1)
    )
    return result.scalar_one_or_none()


def _slugify_workspace_for_user(user_id: UUID) -> str:
    safe = re.sub(r"[^a-z0-9]", "", str(user_id).lower())
    return f"workspace-{safe}"


async def ensure_user_default_workspace(
    user_id: UUID,
    db: AsyncSession,
) -> Project:
    """Return the user's default chat workspace, creating if absent.

    Idempotent. Safe under concurrent first-use: a unique-violation on
    the slug is caught and converted into a re-fetch so two simultaneous
    callers converge on the same row.

    Raises ``LookupError`` if the user has no personal team — callers
    that need a soft failure (e.g. chat creation should still succeed
    even if workspace minting fails) should catch this explicitly.
    """
    if not isinstance(user_id, UUID):
        user_id = UUID(str(user_id))

    existing = await db.execute(
        select(Project)
        .where(Project.owner_id == user_id)
        .where(Project.name == _WORKSPACE_NAME)
        .where(Project.project_kind == PROJECT_KIND_WORKSPACE)
        .limit(1)
    )
    project = existing.scalar_one_or_none()
    if project is not None:
        return project

    team_id = await _get_personal_team_id(db, user_id)
    if team_id is None:
        raise LookupError(f"user {user_id} has no personal team; cannot create default workspace")

    slug = _slugify_workspace_for_user(user_id)

    project = Project(
        name=_WORKSPACE_NAME,
        slug=slug,
        description="Default workspace for chats, CLI tools, and credentials.",
        owner_id=user_id,
        team_id=team_id,
        visibility="private",
        project_kind=PROJECT_KIND_WORKSPACE,
        compute_tier="none",
        runtime=None,
        created_via="empty",
        environment_status="active",
        default_contract_template={},
    )
    db.add(project)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        again = await db.execute(
            select(Project)
            .where(Project.owner_id == user_id)
            .where(Project.name == _WORKSPACE_NAME)
            .where(Project.project_kind == PROJECT_KIND_WORKSPACE)
            .limit(1)
        )
        winner = again.scalar_one_or_none()
        if winner is None:
            raise
        return winner

    db.add(
        ProjectMembership(
            project_id=project.id,
            user_id=user_id,
            role="admin",
            granted_by_id=user_id,
        )
    )
    await db.flush()

    # Provision storage so file/bash/etc. tools work without a separate
    # "set up workspace" step. Mirrors the empty-project create flow at
    # routers/projects.py:_materialize_empty_workspace. Best-effort: a
    # failure here is logged but does not block chat creation — the next
    # tool call can re-attempt or surface the error to the user.
    try:
        from ..config import get_settings
        from ..routers.projects import _materialize_empty_workspace

        await _materialize_empty_workspace(project, get_settings())
        await db.flush()
    except Exception as exc:
        logger.warning(
            "lazy_chat_workspace.materialize_failed user=%s project=%s err=%s",
            user_id,
            project.id,
            exc,
        )

    logger.info(
        "lazy_chat_workspace.created user=%s project=%s slug=%s team=%s volume=%s",
        user_id,
        project.id,
        project.slug,
        team_id,
        project.volume_id,
    )
    return project
