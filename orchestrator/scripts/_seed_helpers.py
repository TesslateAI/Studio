"""Shared helpers for seed scripts.

All seed scripts need a concrete ``(user, team_id)`` pair that already has
an active ``TeamMembership`` — otherwise the publisher's project-creation
step fails its FK/role checks. This module centralizes that lookup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models_auth import User


async def resolve_seeder_user(db: "AsyncSession") -> tuple["User", UUID]:
    """Return the first user with an active TeamMembership plus their team_id.

    Raises:
        RuntimeError: if no such user exists. Seed scripts cannot run on an
            empty DB — create a user via the signup flow or
            ``create_superuser.py`` first.
    """
    from app.models_auth import User
    from app.models_team import TeamMembership

    row = (
        await db.execute(
            select(User, TeamMembership.team_id)
            .join(TeamMembership, TeamMembership.user_id == User.id)
            .where(TeamMembership.is_active.is_(True))
            .order_by(User.created_at)
            .limit(1)
        )
    ).first()
    if row is None:
        raise RuntimeError(
            "no users with an active TeamMembership found — create one via "
            "the signup flow or create_superuser.py before running seeds"
        )
    return row[0], row[1]


__all__ = ["resolve_seeder_user"]
