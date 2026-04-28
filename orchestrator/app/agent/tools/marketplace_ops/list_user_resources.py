"""``list_user_resources`` — read-only inventory for the agent-builder.

Before drafting a child agent, the agent-builder needs to know which MCP
connectors the user has actually connected, what skills are in the
marketplace, what other agents the user already owns, and which
communication destinations are wired up. This tool returns exactly that
slice of the world — and nothing more — so the LLM only proposes things
the user can actually use.

Filter rules (per design — see plan):

* ``connected_mcps`` — only ``UserMcpConfig`` rows with
  ``is_active=True`` AND ``needs_reauth=False``. Inactive or auth-broken
  connectors do not surface; the agent must tell the user to reconnect.
* ``user_owned_agents`` — agents the user authored (not built-ins,
  not system). Used so the builder can avoid duplicate slugs.
* ``communication_destinations`` — only rows the user owns directly.
* ``available_skills`` — published marketplace skill rows.
* ``limits`` — the hard caps the builder must respect when drafting.

Required scope: ``marketplace.author``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select

from ....models import (
    AgentMcpAssignment,
    MarketplaceAgent,
    UserMcpConfig,
)
from ....models_automations import CommunicationDestination
from ....services.automations.scopes import MARKETPLACE_AUTHOR
from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


async def list_user_resources_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Return the inventory dict the agent-builder uses to plan a draft."""
    db = context.get("db")
    user_id = context.get("user_id")
    if db is None or user_id is None:
        return error_output(message="missing db/user_id in execution context")

    allowed_scopes = set(context.get("allowed_scopes") or [])
    if MARKETPLACE_AUTHOR not in allowed_scopes:
        return error_output(message=f"missing required scope: {MARKETPLACE_AUTHOR}")

    # Connected MCPs — joined to MarketplaceAgent for slug + name. Filtered
    # to active, non-needs-reauth rows so the builder only sees usable
    # connectors. The MCP catalog row may be NULL for custom connectors;
    # we still surface those (without a friendly name) so the user knows
    # they exist.
    mcp_rows = (
        await db.execute(
            select(UserMcpConfig, MarketplaceAgent)
            .outerjoin(
                MarketplaceAgent,
                MarketplaceAgent.id == UserMcpConfig.marketplace_agent_id,
            )
            .where(
                UserMcpConfig.user_id == user_id,
                UserMcpConfig.is_active.is_(True),
                UserMcpConfig.needs_reauth.is_(False),
            )
        )
    ).all()

    connected_mcps: list[dict[str, Any]] = []
    for cfg, mp in mcp_rows:
        connected_mcps.append(
            {
                "id": str(cfg.id),
                "marketplace_agent_id": (
                    str(cfg.marketplace_agent_id) if cfg.marketplace_agent_id else None
                ),
                "slug": mp.slug if mp else None,
                "name": mp.name if mp else "Custom connector",
                "scope_level": cfg.scope_level,
                "needs_reauth": cfg.needs_reauth,
            }
        )

    # Agents the user authored — used for slug-collision awareness and
    # so the builder can suggest "you already have X, want me to update
    # it instead?". Excludes built-in / system rows.
    owned_rows = (
        await db.execute(
            select(MarketplaceAgent).where(
                MarketplaceAgent.created_by_user_id == user_id,
                MarketplaceAgent.is_builtin.is_(False),
                MarketplaceAgent.is_system.is_(False),
                MarketplaceAgent.item_type.in_(("agent", "subagent")),
            )
        )
    ).scalars().all()

    user_owned_agents = [
        {
            "id": str(row.id),
            "slug": row.slug,
            "name": row.name,
            "is_published": row.is_published,
            "category": row.category,
        }
        for row in owned_rows
    ]

    # Communication destinations the user owns directly. Team-only
    # destinations are excluded — the builder shouldn't pick a team
    # destination on the user's behalf without explicit selection.
    dest_rows = (
        await db.execute(
            select(CommunicationDestination).where(
                CommunicationDestination.owner_user_id == user_id,
            )
        )
    ).scalars().all()

    communication_destinations = [
        {
            "id": str(row.id),
            "kind": row.kind,
            "name": row.name,
        }
        for row in dest_rows
    ]

    # Published skills (item_type='skill'). Returned as a small catalog
    # so the builder knows what reusable instruction bundles exist.
    skill_rows = (
        await db.execute(
            select(MarketplaceAgent).where(
                MarketplaceAgent.item_type == "skill",
                MarketplaceAgent.is_published.is_(True),
            )
        )
    ).scalars().all()

    available_skills = [
        {
            "id": str(row.id),
            "slug": row.slug,
            "name": row.name,
            "description": row.description,
        }
        for row in skill_rows
    ]

    logger.info(
        "marketplace_ops.list_user_resources user=%s mcps=%d agents=%d dests=%d skills=%d",
        user_id,
        len(connected_mcps),
        len(user_owned_agents),
        len(communication_destinations),
        len(available_skills),
    )

    payload = {
        "connected_mcps": connected_mcps,
        "user_owned_agents": user_owned_agents,
        "communication_destinations": communication_destinations,
        "available_skills": available_skills,
        "limits": {
            "max_depth": 1,
            "default_max_compute_tier": 0,
            "default_max_spend_per_run_usd": "0.10",
            "draft_only": True,
        },
    }
    return success_output(
        message=(
            f"User has {len(connected_mcps)} connected MCP(s), "
            f"{len(user_owned_agents)} owned agent(s), "
            f"{len(communication_destinations)} communication destination(s)."
        ),
        # ``content`` is propagated to the LLM by format_tool_result; the
        # ``connected_mcps`` etc. top-level fields are stripped on the
        # agent side, so we serialize the structured data here so the
        # model can actually read slugs and IDs.
        content=json.dumps(payload, indent=2),
        **payload,
    )


def register_list_user_resources_tool(registry):
    registry.register(
        Tool(
            name="list_user_resources",
            description=(
                "Inventory the resources the agent-builder may compose into a "
                "new draft agent: connected MCP connectors, owned agents, "
                "communication destinations, and published skills. Returns "
                "only resources currently usable — disconnected / "
                "needs-reauth MCPs are excluded. Required scope: "
                "marketplace.author."
            ),
            parameters={
                "type": "object",
                "properties": {},
            },
            executor=list_user_resources_executor,
            category=ToolCategory.PROJECT,
            state_serializable=True,
            holds_external_state=False,
        )
    )


# AgentMcpAssignment is imported for relationship clarity even though we
# don't query it directly here — the agent uses assign_mcp to insert
# rows after this tool surfaces the available connectors.
_ = AgentMcpAssignment
