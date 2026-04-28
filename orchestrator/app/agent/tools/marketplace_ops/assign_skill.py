"""``assign_skill`` — link a skill to an agent.

Inserts an :class:`AgentSkillAssignment` row scoped to the current user.
The unique constraint ``(agent_id, skill_id, user_id)`` collapses
duplicates — re-running the tool is idempotent.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ....services.automations.scopes import MARKETPLACE_AUTHOR
from ....models import AgentSkillAssignment, MarketplaceAgent
from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


async def assign_skill_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    agent_id_raw = params.get("agent_id")
    skill_id_raw = params.get("skill_id")
    if not agent_id_raw or not skill_id_raw:
        return error_output(message="agent_id and skill_id are required")

    db = context.get("db")
    user_id = context.get("user_id")
    if db is None or user_id is None:
        return error_output(message="missing db/user_id in execution context")

    allowed_scopes = set(context.get("allowed_scopes") or [])
    if MARKETPLACE_AUTHOR not in allowed_scopes:
        return error_output(message=f"missing required scope: {MARKETPLACE_AUTHOR}")

    try:
        agent_id = UUID(str(agent_id_raw))
        skill_id = UUID(str(skill_id_raw))
    except (TypeError, ValueError):
        return error_output(message="invalid agent_id or skill_id")

    # Existence + ownership checks. The agent must be ours; the skill
    # row must exist (built-ins are public so item_type=='skill' rows
    # owned by anyone are valid targets).
    agent = (
        await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        return error_output(message=f"agent {agent_id} not found")
    if agent.created_by_user_id != user_id and agent.forked_by_user_id != user_id:
        return error_output(message="not the owner of this agent")

    skill_row = (
        await db.execute(
            select(MarketplaceAgent.id, MarketplaceAgent.item_type).where(
                MarketplaceAgent.id == skill_id
            )
        )
    ).first()
    if skill_row is None:
        return error_output(message=f"skill {skill_id} not found")
    if skill_row.item_type != "skill":
        return error_output(
            message=f"target {skill_id} is not a skill (item_type={skill_row.item_type!r})"
        )

    team_id = context.get("team_id")
    db.add(
        AgentSkillAssignment(
            agent_id=agent_id,
            skill_id=skill_id,
            user_id=user_id,
            team_id=team_id,
            enabled=True,
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        # UniqueConstraint(agent_id, skill_id, user_id) — duplicate is
        # the success case here; the link already exists.
        await db.rollback()
        logger.info(
            "marketplace_ops.assign_skill duplicate ignored agent=%s skill=%s user=%s",
            agent_id,
            skill_id,
            user_id,
        )
        return success_output(
            message="Skill already assigned to agent",
            ok=True,
            agent_id=str(agent_id),
            skill_id=str(skill_id),
            duplicate=True,
        )

    logger.info(
        "marketplace_ops.assign_skill agent=%s skill=%s user=%s",
        agent_id,
        skill_id,
        user_id,
    )
    return success_output(
        message="Skill assigned to agent",
        ok=True,
        agent_id=str(agent_id),
        skill_id=str(skill_id),
    )


def register_assign_skill_tool(registry):
    registry.register(
        Tool(
            name="assign_skill",
            description=(
                "Link a marketplace skill to an agent owned by the current user. "
                "Idempotent — re-running with the same pair is a no-op. "
                "Required scope: marketplace.author."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "skill_id": {"type": "string"},
                },
                "required": ["agent_id", "skill_id"],
            },
            executor=assign_skill_executor,
            category=ToolCategory.PROJECT,
            state_serializable=True,
            holds_external_state=False,
        )
    )
