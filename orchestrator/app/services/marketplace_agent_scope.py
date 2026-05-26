"""Shared agent-binding scope resolver.

Defines what "agent X is reachable for user Y" means in a single place
so the automation API, the apps installer, and the agent-run worker all
agree. Without this, the picker (``GET /api/marketplace/my-agents``) and
the PATCH path could (and did, prior to TC-03 Bug #21) disagree —
yielding a multi-tenancy violation where one team's user could bind
another team's private agent by direct PATCH.

The rules in one paragraph:

1. The row in ``marketplace_agents`` must exist.
2. The row's ``item_type`` must be the runnable kind. Skills, MCP
   servers, subagent specs, and deployment targets share the same table
   but are not runnable as ``agent.run`` actions.
3. The row's ``is_active`` must be ``True``.
4. The user must own the row OR the row must be ``is_system=True``.
   "Own" means: there is a ``user_purchased_agents`` row keyed by the
   caller's active team (preferred) or falling back to the caller's
   user id when no active team is set. Mirrors the picker query
   verbatim.

Superusers bypass step 4 only; steps 1–3 still apply because they are
correctness invariants, not authorization checks.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MarketplaceAgent, User, UserPurchasedAgent

__all__ = [
    "AgentScopeError",
    "NON_RUNNABLE_ITEM_TYPES",
    "RUNNABLE_AGENT_ITEM_TYPE",
    "resolve_agent_in_user_scope",
]


# Item types that are persisted in ``marketplace_agents`` but are NOT
# runnable as ``agent.run`` actions — skills are loaded via load_skill,
# MCPs are connectors, subagents are template specs, deployment_targets
# are CI/CD adapters. Kept as a frozenset so the symbol can be imported
# anywhere a query needs to filter them out without re-listing the
# strings inline. Mirrors the ``notin_(...)`` filter in
# ``routers/marketplace.get_user_agents``.
NON_RUNNABLE_ITEM_TYPES: Final[frozenset[str]] = frozenset(
    {"skill", "subagent", "mcp_server", "deployment_target"}
)
RUNNABLE_AGENT_ITEM_TYPE: Final[str] = "agent"


class AgentScopeError(Exception):
    """Raised when an agent can't be bound by the requesting user.

    Carries a stable machine-readable :attr:`reason` token so callers
    can map it to a typed HTTP code (or a worker-side terminal failure)
    without string-matching the message. The message itself is shaped
    for direct surfacing to API clients.
    """

    REASON_NOT_FOUND: Final[str] = "agent_not_found"
    REASON_WRONG_TYPE: Final[str] = "agent_wrong_item_type"
    REASON_INACTIVE: Final[str] = "agent_inactive"
    REASON_NOT_IN_LIBRARY: Final[str] = "agent_not_in_library"

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


async def resolve_agent_in_user_scope(
    db: AsyncSession, *, agent_id: UUID, user: User
) -> MarketplaceAgent:
    """Return the agent if ``user`` may bind it; else raise :class:`AgentScopeError`.

    Args:
        db: Async session — read-only; caller owns commit semantics.
        agent_id: The ``marketplace_agents.id`` to resolve.
        user: The caller. Owner check uses ``default_team_id`` first
            (matching the picker), falling back to ``user.id``. Superusers
            skip the library check but still require existence + active +
            correct ``item_type``.

    Raises:
        AgentScopeError: With a stable ``reason`` token. The four reasons
            are exposed as class constants so call sites can branch
            without string-matching the message.
    """
    agent = (
        await db.execute(
            select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id)
        )
    ).scalar_one_or_none()
    if agent is None:
        raise AgentScopeError(
            AgentScopeError.REASON_NOT_FOUND,
            f"agent {agent_id} does not exist",
        )
    if agent.item_type != RUNNABLE_AGENT_ITEM_TYPE:
        raise AgentScopeError(
            AgentScopeError.REASON_WRONG_TYPE,
            (
                f"agent {agent_id} has item_type={agent.item_type!r}; "
                f"only {RUNNABLE_AGENT_ITEM_TYPE!r} can run"
            ),
        )
    if not agent.is_active:
        raise AgentScopeError(
            AgentScopeError.REASON_INACTIVE,
            f"agent {agent_id} is deactivated",
        )

    if getattr(user, "is_superuser", False) or agent.is_system:
        return agent

    team_id = getattr(user, "default_team_id", None)
    ownership_filter = (
        UserPurchasedAgent.team_id == team_id
        if team_id is not None
        else UserPurchasedAgent.user_id == user.id
    )
    purchase_id = (
        await db.execute(
            select(UserPurchasedAgent.id)
            .where(ownership_filter, UserPurchasedAgent.agent_id == agent_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if purchase_id is None:
        raise AgentScopeError(
            AgentScopeError.REASON_NOT_IN_LIBRARY,
            (
                f"agent {agent_id} is not in your library — install it "
                "from the marketplace before binding"
            ),
        )
    return agent
