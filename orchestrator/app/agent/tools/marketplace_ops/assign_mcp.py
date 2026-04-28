"""``assign_mcp`` — link an MCP server to an agent.

Inserts an :class:`AgentMcpAssignment` row scoped to the current user.
The unique constraint ``(agent_id, mcp_config_id, user_id)`` collapses
duplicates so the call is idempotent.

The ``scopes`` parameter is captured for audit but the actual scope
enforcement happens at MCP call time via the ``mcp.*`` scope prefix in
the contract — assignment alone does not grant any new capability.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ....services.automations.scopes import MARKETPLACE_AUTHOR
from ....models import AgentMcpAssignment, MarketplaceAgent, UserMcpConfig
from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


async def assign_mcp_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    agent_id_raw = params.get("agent_id")
    mcp_config_id_raw = params.get("mcp_config_id")
    if not agent_id_raw or not mcp_config_id_raw:
        return error_output(message="agent_id and mcp_config_id are required")

    db = context.get("db")
    user_id = context.get("user_id")
    if db is None or user_id is None:
        return error_output(message="missing db/user_id in execution context")

    allowed_scopes = set(context.get("allowed_scopes") or [])
    if MARKETPLACE_AUTHOR not in allowed_scopes:
        return error_output(message=f"missing required scope: {MARKETPLACE_AUTHOR}")

    try:
        agent_id = UUID(str(agent_id_raw))
        mcp_config_id = UUID(str(mcp_config_id_raw))
    except (TypeError, ValueError):
        return error_output(message="invalid agent_id or mcp_config_id")

    scopes = params.get("scopes") or []
    if not isinstance(scopes, list):
        return error_output(message="scopes must be a list of strings")

    # Existence + ownership checks. The agent and MCP config must both
    # belong to the current user.
    agent = (
        await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        return error_output(message=f"agent {agent_id} not found")
    if agent.created_by_user_id != user_id and agent.forked_by_user_id != user_id:
        return error_output(message="not the owner of this agent")

    mcp_cfg = (
        await db.execute(
            select(UserMcpConfig.id, UserMcpConfig.user_id).where(
                UserMcpConfig.id == mcp_config_id
            )
        )
    ).first()
    if mcp_cfg is None:
        return error_output(message=f"mcp_config {mcp_config_id} not found")
    if mcp_cfg.user_id != user_id:
        return error_output(message="not the owner of this MCP config")

    team_id = context.get("team_id")
    db.add(
        AgentMcpAssignment(
            agent_id=agent_id,
            mcp_config_id=mcp_config_id,
            user_id=user_id,
            team_id=team_id,
            enabled=True,
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.info(
            "marketplace_ops.assign_mcp duplicate ignored agent=%s mcp=%s user=%s",
            agent_id,
            mcp_config_id,
            user_id,
        )
        return success_output(
            message="MCP already assigned to agent",
            ok=True,
            agent_id=str(agent_id),
            mcp_config_id=str(mcp_config_id),
            duplicate=True,
            requested_scopes=scopes,
        )

    logger.info(
        "marketplace_ops.assign_mcp agent=%s mcp=%s user=%s scopes=%s",
        agent_id,
        mcp_config_id,
        user_id,
        scopes,
    )
    return success_output(
        message="MCP assigned to agent",
        ok=True,
        agent_id=str(agent_id),
        mcp_config_id=str(mcp_config_id),
        requested_scopes=scopes,
    )


def register_assign_mcp_tool(registry):
    registry.register(
        Tool(
            name="assign_mcp",
            description=(
                "Link a user-installed MCP server to an agent owned by the "
                "current user. The 'scopes' arg is recorded for audit; the "
                "actual mcp.* scope enforcement happens at call time via the "
                "automation contract. Required scope: marketplace.author."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "mcp_config_id": {"type": "string"},
                    "scopes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Requested mcp.* scopes for audit",
                    },
                },
                "required": ["agent_id", "mcp_config_id"],
            },
            executor=assign_mcp_executor,
            category=ToolCategory.PROJECT,
            state_serializable=True,
            holds_external_state=False,
        )
    )
