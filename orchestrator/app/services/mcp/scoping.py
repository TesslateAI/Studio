"""Three-tier scope resolution for MCP connectors.

Precedence ``project > user > team`` — i.e. a project-scoped row overrides a
user-scoped one, which overrides any team-scoped one. Multiple team rows are
aggregated across the user's active team memberships.

Custom connectors (``marketplace_agent_id IS NULL``) are *never* deduped —
two BYO servers with the same URL can coexist across scopes because they
often point to different instances.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import AgentMcpAssignment, UserMcpConfig
from ...models_team import TeamMembership

logger = logging.getLogger(__name__)

# Higher rank wins when two rows dedupe on the same marketplace_agent_id.
_SCOPE_RANK = {"project": 3, "user": 2, "team": 1}


async def resolve_mcp_configs(
    db: AsyncSession,
    *,
    user_id: UUID,
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    agent_id: UUID | str | None = None,
) -> list[UserMcpConfig]:
    """Return the effective set of active MCP configs for (user, team, project).

    Algorithm:
    1. Collect candidate rows across three scopes:
       - ``project`` rows where ``project_id`` matches.
       - ``user`` rows owned by ``user_id``.
       - ``team`` rows for any active team the user belongs to (including the
         request's ``team_id`` if supplied).
    2. When ``agent_id`` is set, intersect with :class:`AgentMcpAssignment`
       enabled entries so only explicitly-assigned servers reach the agent.
    3. Deduplicate catalog rows on ``marketplace_agent_id`` keeping the
       highest-rank scope. Custom connectors (no ``marketplace_agent_id``) are
       never deduped.
    """
    # Active team memberships for the user → used for `team`-scope aggregation.
    team_ids = await _active_team_ids(db, user_id=user_id)
    if team_id is not None:
        team_ids.add(team_id)

    conditions = [
        # user-scope: owned rows
        (UserMcpConfig.user_id == user_id) & (UserMcpConfig.scope_level == "user"),
    ]
    if team_ids:
        conditions.append(
            (UserMcpConfig.scope_level == "team")
            & (UserMcpConfig.team_id.in_(team_ids))
        )
    if project_id is not None:
        conditions.append(
            (UserMcpConfig.scope_level == "project")
            & (UserMcpConfig.project_id == project_id)
        )

    stmt = (
        select(UserMcpConfig)
        .options(selectinload(UserMcpConfig.marketplace_agent))
        .where(UserMcpConfig.is_active.is_(True))
        .where(or_(*conditions))
    )

    if agent_id is not None:
        # Intersection with AgentMcpAssignment — MCP server must be attached
        # to the specific agent being run. Note: we intentionally do NOT
        # filter by assignment.user_id here — for team-scope MCPs the
        # enablement may have been set up by any team member (typically an
        # admin), and gating on the current user would hide it from peers.
        stmt = (
            stmt.join(
                AgentMcpAssignment,
                AgentMcpAssignment.mcp_config_id == UserMcpConfig.id,
            )
            .where(
                AgentMcpAssignment.agent_id == agent_id,
                AgentMcpAssignment.enabled.is_(True),
            )
        )

    rows: list[UserMcpConfig] = list((await db.execute(stmt)).scalars().all())
    return _apply_precedence(rows)


async def _active_team_ids(db: AsyncSession, *, user_id: UUID) -> set[UUID]:
    """Set of team IDs the user is an active member of."""
    stmt = select(TeamMembership.team_id).where(
        TeamMembership.user_id == user_id,
        TeamMembership.is_active.is_(True),
    )
    result = await db.execute(stmt)
    return set(result.scalars().all())


def _apply_precedence(rows: Iterable[UserMcpConfig]) -> list[UserMcpConfig]:
    """Collapse catalog duplicates by keeping the highest-rank scope.

    Custom connectors (marketplace_agent_id IS NULL) pass through unchanged.
    """
    best_by_agent: dict[UUID, UserMcpConfig] = {}
    customs: list[UserMcpConfig] = []
    for row in rows:
        if row.marketplace_agent_id is None:
            customs.append(row)
            continue
        key = row.marketplace_agent_id
        existing = best_by_agent.get(key)
        if existing is None or _SCOPE_RANK.get(row.scope_level, 0) > _SCOPE_RANK.get(
            existing.scope_level, 0
        ):
            best_by_agent[key] = row
    return [*best_by_agent.values(), *customs]


__all__ = ["resolve_mcp_configs"]
