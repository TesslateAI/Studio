"""``create_agent`` — draft a new :class:`MarketplaceAgent` row.

The agent-builder skill calls this to author a child agent. The row is
inserted in DRAFT state (``is_published=False``); a human must publish
it via the UI. Provenance is stamped via ``created_by_automation_id``
so the dispatcher's parent-chain walker can follow the relationship
later.

Required scope: ``marketplace.author`` (see :mod:`app.services.automations.scopes`).
"""

from __future__ import annotations

import logging
import re
import secrets
from typing import Any

from sqlalchemy import select

from ....services.automations.scopes import MARKETPLACE_AUTHOR
from ....services.marketplace_constants import LOCAL_SOURCE_ID
from ....models import MarketplaceAgent, UserPurchasedAgent
from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


_VALID_ITEM_TYPES = {"agent", "subagent"}


def _slugify_base(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "agent"


async def _allocate_slug(db, name: str) -> str:
    """Allocate a short, mention-friendly slug.

    The legacy ``create_custom_agent`` router uses
    ``{name}-{user_id}-{timestamp}`` which produces 60-char slugs that are
    impossible to type as a chat mention. Agent-builder is the
    user-facing path, so we trade the deterministic legacy form for a
    short ``{name}-{4-char hex}`` slug with a uniqueness retry loop.
    """
    base = _slugify_base(name)
    for _ in range(8):
        candidate = f"{base}-{secrets.token_hex(2)}"
        existing = (
            await db.execute(
                select(MarketplaceAgent.id).where(MarketplaceAgent.slug == candidate)
            )
        ).first()
        if existing is None:
            return candidate
    # Defensive fallback — 6 hex bytes is 16M; effectively impossible to
    # exhaust naturally, but we don't want an infinite loop.
    return f"{base}-{secrets.token_hex(6)}"


async def create_agent_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Create a draft MarketplaceAgent row owned by the current user.

    Inserts the row with ``is_published=False`` regardless of input.
    Stamps ``created_by_automation_id`` from
    ``context['automation_id']`` when present so we can walk the
    provenance chain later.
    """
    name = params.get("name")
    description = params.get("description")
    system_prompt = params.get("system_prompt")
    if not name or not description or not system_prompt:
        return error_output(
            message="name, description, and system_prompt are required"
        )

    db = context.get("db")
    user_id = context.get("user_id")
    if db is None or user_id is None:
        return error_output(message="missing db/user_id in execution context")

    # Scope check — defense in depth. The view-scoped registry should
    # already strip this tool when the run lacks the scope, but we
    # verify here so a misconfigured registry can't bypass the gate.
    allowed_scopes = set(context.get("allowed_scopes") or [])
    if MARKETPLACE_AUTHOR not in allowed_scopes:
        return error_output(
            message=f"missing required scope: {MARKETPLACE_AUTHOR}"
        )

    item_type = params.get("item_type", "agent")
    if item_type not in _VALID_ITEM_TYPES:
        return error_output(
            message=f"item_type must be one of {sorted(_VALID_ITEM_TYPES)}"
        )

    model = params.get("model")
    tool_allowlist = params.get("tool_allowlist") or []
    if not isinstance(tool_allowlist, list):
        return error_output(message="tool_allowlist must be a list")

    automation_id = context.get("automation_id")
    slug = await _allocate_slug(db, name)

    agent = MarketplaceAgent(
        name=name,
        slug=slug,
        description=description,
        long_description=description,
        category=params.get("category", "custom"),
        item_type=item_type,
        system_prompt=system_prompt,
        agent_type=params.get("agent_type"),
        tools=tool_allowlist,
        model=model,
        is_forkable=False,
        forked_by_user_id=user_id,
        created_by_user_id=user_id,
        created_by_automation_id=automation_id,
        config={},
        icon=params.get("icon", "🤖"),
        pricing_type="free",
        price=0,
        source_type="open",
        source_id=LOCAL_SOURCE_ID,
        requires_user_keys=False,
        downloads=0,
        rating=5.0,
        reviews_count=0,
        features=["Custom agent"],
        required_models=[model] if model else [],
        tags=params.get("tags", ["custom"]),
        is_featured=False,
        is_active=True,
        # CRITICAL: tool-driven creates are ALWAYS drafts. Publishing is
        # a UI-only action that requires a human to flip the bit.
        is_published=False,
    )
    db.add(agent)
    await db.flush()

    # Mirror the existing custom-agent router: add the new agent to the
    # creator's library so they can immediately wire it into a project.
    db.add(
        UserPurchasedAgent(
            user_id=user_id,
            agent_id=agent.id,
            purchase_type="free",
            is_active=True,
        )
    )
    await db.commit()
    await db.refresh(agent)

    draft_url = f"/marketplace/agents/{agent.slug}?draft=1"
    logger.info(
        "marketplace_ops.create_agent agent=%s slug=%s user=%s automation=%s",
        agent.id,
        agent.slug,
        user_id,
        automation_id,
    )
    return success_output(
        message=(
            f"Drafted agent {agent.name!r}. "
            f"agent_id={agent.id} slug={agent.slug} is_published=False. "
            f"Use this exact agent_id for any subsequent assign_mcp / "
            f"assign_skill / attach_schedule / request_review call."
        ),
        agent_id=str(agent.id),
        slug=agent.slug,
        draft_url=draft_url,
        is_published=False,
    )


def register_create_agent_tool(registry):
    """Register the ``create_agent`` tool."""
    registry.register(
        Tool(
            name="create_agent",
            description=(
                "Draft a new marketplace agent (agent, subagent). The row is "
                "inserted in DRAFT state — a human must publish it from the UI "
                "before it appears in the marketplace. Required scope: "
                "marketplace.author."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Display name"},
                    "description": {"type": "string", "description": "One-line summary"},
                    "system_prompt": {"type": "string", "description": "Full system prompt"},
                    "model": {"type": "string", "description": "Preferred model id"},
                    "tool_allowlist": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Names of tools the agent may invoke",
                    },
                    "category": {"type": "string", "description": "Marketplace category"},
                    "item_type": {
                        "type": "string",
                        "enum": ["agent", "subagent"],
                        "description": "Defaults to 'agent'",
                    },
                    "icon": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "description", "system_prompt"],
            },
            executor=create_agent_executor,
            category=ToolCategory.PROJECT,
            # Inputs are JSON-clean; output is the new row's id + url.
            state_serializable=True,
            # Database insert — no socket, MCP stream, or PTY held open.
            holds_external_state=False,
        )
    )
