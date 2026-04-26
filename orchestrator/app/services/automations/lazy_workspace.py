"""Per-user automation workspace project — lazy-created on first use.

The Phase 5 plan introduces a ``user_automation_workspace`` scope on
``automation_definitions``. When an automation with that scope fires for
the first time the dispatcher needs *some* Project to attribute spend,
files, and run artifacts to. Rather than pre-creating one for every
user at signup (most users never trigger an automation that needs one),
the workspace is created lazily by this helper.

Lazy invariants:

- Exactly one row per user with ``name='~automations~'``,
  ``project_kind='workspace'``, ``compute_tier='none'``.
- Idempotent: a second call returns the same row without inserting.
- Tied to the user's personal team so RBAC checks pass uniformly.
- Empty ``default_contract_template={}`` — the user can fill it later.

Callers (Phase 5 onward):

- ``services.automations.dispatcher`` — when the resolved
  ``workspace_scope`` is ``user_automation_workspace`` and the
  definition's ``workspace_project_id`` is NULL.
- DO NOT call from signup, login, or any "warm-up" hook. The whole
  point is "lazy on first use".

See ``/Users/smirk/.claude/plans/ultrathink-i-want-to-glittery-pond.md``
section "Workspace model".
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import PROJECT_KIND_WORKSPACE, Project
from ...models_team import Team

if TYPE_CHECKING:  # pragma: no cover
    pass

logger = logging.getLogger(__name__)


# Reserved name. Tilde-prefixed so it sorts to the bottom of project
# listings and never collides with a user-supplied project name (the UI
# rejects names starting with '~').
_WORKSPACE_NAME = "~automations~"


__all__ = [
    "ensure_user_automation_workspace",
]


async def _get_personal_team_id(db: AsyncSession, user_id: UUID) -> UUID | None:
    """Look up the user's personal team id, if any.

    Personal teams are created at signup via the user-manager's
    ``on_after_register`` hook; they have ``is_personal=True`` and
    ``created_by_id == user_id``.
    """
    result = await db.execute(
        select(Team.id)
        .where(Team.created_by_id == user_id)
        .where(Team.is_personal.is_(True))
        .limit(1)
    )
    return result.scalar_one_or_none()


def _slugify_workspace_for_user(user_id: UUID) -> str:
    """Deterministic slug for the workspace project.

    Using the user_id keeps the slug globally unique without needing a
    counter / collision retry. The leading ``~`` mirrors the name and
    keeps these projects visually grouped in any slug-sorted UI.
    """
    safe = re.sub(r"[^a-z0-9]", "", str(user_id).lower())
    return f"automations-{safe}"


async def ensure_user_automation_workspace(
    user_id: UUID,
    db: AsyncSession,
) -> Project:
    """Return the user's automation-workspace Project, creating if absent.

    Idempotent. Safe under concurrent first-use: a unique-violation on
    the slug is caught and converted into a re-fetch so two simultaneous
    dispatches converge on the same row.

    Raises ``LookupError`` if the user has no personal team (which
    should be impossible in practice but we surface it loudly rather
    than silently inserting an orphan project).
    """
    if not isinstance(user_id, UUID):
        # Accept stringified UUIDs from the dispatcher path uniformly.
        user_id = UUID(str(user_id))

    # Fast path: existing row.
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
        raise LookupError(
            f"user {user_id} has no personal team; cannot create automation workspace"
        )

    slug = _slugify_workspace_for_user(user_id)

    project = Project(
        name=_WORKSPACE_NAME,
        slug=slug,
        description="Lazy-created workspace for user-scoped automations.",
        owner_id=user_id,
        team_id=team_id,
        visibility="private",
        project_kind=PROJECT_KIND_WORKSPACE,
        compute_tier="none",
        runtime=None,
        default_contract_template={},
    )
    db.add(project)
    try:
        await db.flush()
    except IntegrityError:
        # Lost the race with a sibling worker. Re-fetch and return the
        # winner's row; do NOT raise — the post-condition is satisfied.
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
            # Constraint failed for some other reason — re-raise so the
            # caller surfaces it instead of silently swallowing.
            raise
        return winner

    logger.info(
        "lazy_workspace.created user=%s project=%s slug=%s team=%s",
        user_id,
        project.id,
        project.slug,
        team_id,
    )
    return project
