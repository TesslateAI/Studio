"""Marketplace authoring tools — the agent-builder skill's tool surface.

Six tools that together let an automation draft a child agent + attach a
schedule to it (depth-1 cap). All tools require the
``marketplace.author`` and/or ``automations.write`` scope (see
:mod:`app.services.automations.scopes`); none of them publish anything to the public
marketplace — publishing is a UI-only action that flips
``MarketplaceAgent.is_published=True`` after a human review.

Tools:
- ``create_agent`` — insert a draft :class:`MarketplaceAgent` row.
- ``update_agent`` — patch draft fields. Rejects rows where
  ``is_published=True``.
- ``assign_skill`` — link a skill to an agent
  (``AgentSkillAssignment``).
- ``assign_mcp`` — link an MCP server to an agent
  (``AgentMcpAssignment``).
- ``attach_schedule`` — create a child :class:`AutomationDefinition`
  with depth=1, validating the contract is a legal restriction of the
  parent.
- ``request_grant`` — register an approval card asking the human for a
  capability the run needs but doesn't have. Wait-cap pattern.

See ``/Users/smirk/.claude/plans/ultrathink-i-want-to-glittery-pond.md``
section "Agent-builds-agents — just a skill".
"""

from .assign_mcp import register_assign_mcp_tool
from .assign_skill import register_assign_skill_tool
from .attach_schedule import register_attach_schedule_tool
from .create_agent import register_create_agent_tool
from .list_user_resources import register_list_user_resources_tool
from .request_grant import register_request_grant_tool
from .request_review import register_request_review_tool
from .update_agent import register_update_agent_tool


def register_all_marketplace_ops_tools(registry):
    """Register all marketplace authoring tools (the agent-builder surface)."""
    register_create_agent_tool(registry)
    register_update_agent_tool(registry)
    register_assign_skill_tool(registry)
    register_assign_mcp_tool(registry)
    register_attach_schedule_tool(registry)
    register_request_grant_tool(registry)
    register_list_user_resources_tool(registry)
    register_request_review_tool(registry)


__all__ = [
    "register_all_marketplace_ops_tools",
    "register_assign_mcp_tool",
    "register_assign_skill_tool",
    "register_attach_schedule_tool",
    "register_create_agent_tool",
    "register_list_user_resources_tool",
    "register_request_grant_tool",
    "register_request_review_tool",
    "register_update_agent_tool",
]
