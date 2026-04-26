"""``update_agent`` — patch draft fields on a MarketplaceAgent.

Refuses to touch a published row (``is_published=True``). Refuses to
touch any row not owned by the current user. The patch dict is
intentionally narrow: a small whitelist of safe fields, never the
``is_published`` / ``is_builtin`` / ``is_system`` flags.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select

from ....services.automations.scopes import MARKETPLACE_AUTHOR
from ....models import MarketplaceAgent
from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


# Fields the agent-builder tool may patch on a draft row. Anything not
# in this list is silently dropped (with a warning in the response) so
# a typo or model hallucination can't flip privileged flags.
_PATCHABLE_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "description",
        "long_description",
        "category",
        "system_prompt",
        "agent_type",
        "tools",
        "model",
        "icon",
        "tags",
        "features",
        "config",
    }
)


# Fields that must NEVER be set via this tool. Listed explicitly so the
# response can name the offender rather than just dropping it silently.
_FORBIDDEN_FIELDS: frozenset[str] = frozenset(
    {
        "is_published",
        "is_builtin",
        "is_system",
        "is_featured",
        "creator_user_id",
        "created_by_user_id",
        "created_by_automation_id",
        "id",
        "slug",
        "pricing_type",
        "price",
        "stripe_price_id",
        "stripe_product_id",
    }
)


async def update_agent_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Patch a draft MarketplaceAgent's whitelisted fields."""
    agent_id_raw = params.get("agent_id")
    patch = params.get("patch")
    if not agent_id_raw or not isinstance(patch, dict):
        return error_output(message="agent_id and patch (dict) are required")

    db = context.get("db")
    user_id = context.get("user_id")
    if db is None or user_id is None:
        return error_output(message="missing db/user_id in execution context")

    allowed_scopes = set(context.get("allowed_scopes") or [])
    if allowed_scopes and MARKETPLACE_AUTHOR not in allowed_scopes:
        return error_output(message=f"missing required scope: {MARKETPLACE_AUTHOR}")

    try:
        agent_id = UUID(str(agent_id_raw))
    except (TypeError, ValueError):
        return error_output(message=f"invalid agent_id: {agent_id_raw!r}")

    agent = (
        await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        return error_output(message=f"agent {agent_id} not found")

    # Ownership: the creator/forker may patch their own drafts. Built-ins
    # and system rows are never patchable via this tool.
    if agent.is_builtin or agent.is_system:
        return error_output(
            message="cannot patch built-in or system agents via this tool"
        )
    if agent.created_by_user_id != user_id and agent.forked_by_user_id != user_id:
        return error_output(message="not the owner of this agent")

    # Hard reject if already published. The UI is the only path that
    # can flip is_published; once flipped, edits go through a dedicated
    # router that creates a new draft version, not via this tool.
    if agent.is_published:
        return error_output(
            message="agent is already published; create a fork to edit"
        )

    forbidden = sorted(set(patch.keys()) & _FORBIDDEN_FIELDS)
    if forbidden:
        return error_output(
            message=f"forbidden fields in patch: {forbidden}",
            suggestion="Drop these keys from the patch dict",
        )

    applied: dict[str, Any] = {}
    dropped: list[str] = []
    for key, value in patch.items():
        if key in _PATCHABLE_FIELDS:
            setattr(agent, key, value)
            applied[key] = value
        else:
            dropped.append(key)

    await db.commit()
    await db.refresh(agent)

    logger.info(
        "marketplace_ops.update_agent agent=%s applied=%s dropped=%s user=%s",
        agent.id,
        sorted(applied.keys()),
        dropped,
        user_id,
    )
    return success_output(
        message=f"Updated agent {agent.name!r}",
        ok=True,
        agent_id=str(agent.id),
        applied=list(applied.keys()),
        dropped=dropped,
    )


def register_update_agent_tool(registry):
    """Register the ``update_agent`` tool."""
    registry.register(
        Tool(
            name="update_agent",
            description=(
                "Patch fields on a DRAFT MarketplaceAgent owned by the current "
                "user. Rejects published rows, built-ins, and system agents. "
                "Cannot flip is_published — that's UI-only. Required scope: "
                "marketplace.author."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "UUID of the draft agent"},
                    "patch": {
                        "type": "object",
                        "description": "Dict of {field: new_value} pairs",
                    },
                },
                "required": ["agent_id", "patch"],
            },
            executor=update_agent_executor,
            category=ToolCategory.PROJECT,
            # Patch dict in, ack dict out.
            state_serializable=True,
            holds_external_state=False,
        )
    )
