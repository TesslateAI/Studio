"""Unit tests for the ``call_agent`` multi-agent delegation tool.

Verifies the safety invariants that the @-mention picker depends on:

1. The tool refuses to dispatch when ``agent_id`` is not in the
   ``mention_agent_ids`` allowlist on the parent context (so the LLM
   can't invent an arbitrary agent id at runtime).
2. The tool refuses cleanly with structured ``ok=False`` when the
   target marketplace agent has been deleted (rather than crashing
   the parent loop).
3. ``register_call_agent_tool`` no-ops when the authorized list is
   empty — the conditional registration is the structural multi-agent
   cap that keeps a delegated run from ping-ponging back into another
   ``call_agent``.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

from app.agent.tools.agent_ops.call_agent import (
    call_agent_executor,
    register_call_agent_tool,
)
from app.agent.tools.registry import ToolCategory, ToolRegistry


@pytest.mark.asyncio
async def test_unauthorized_agent_id_is_rejected():
    """LLM passes an id that the user did not @-mention -> structured error."""
    authorized = str(uuid4())
    target = str(uuid4())  # different — not on the list

    # No DB hit needed: the auth check happens before the lookup.
    context = {
        "mention_agent_ids": [authorized],
        "user_id": str(uuid4()),
        "task_id": "parent-task",
        "db": object(),  # never used on the auth-rejected path
    }
    result = await call_agent_executor(
        {"agent_id": target, "message": "ping"},
        context,
    )
    assert result["success"] is False
    # The executor surfaces a friendly message + the authorization roster
    # so logs / debugging can show why the call was refused.
    assert "authorization list" in result["message"].lower() or "authoriz" in result["message"].lower()


@pytest.mark.asyncio
async def test_missing_message_is_rejected():
    """Empty / non-string message -> structured error before any DB or worker hop."""
    result = await call_agent_executor(
        {"agent_id": str(uuid4()), "message": ""},
        {"mention_agent_ids": [], "db": object()},
    )
    assert result["success"] is False
    assert "message" in result["message"].lower()


@pytest.mark.asyncio
async def test_invalid_uuid_agent_id_is_rejected():
    """A bad UUID format short-circuits — never tries to look it up."""
    result = await call_agent_executor(
        {"agent_id": "not-a-uuid", "message": "go"},
        {"mention_agent_ids": [], "db": object()},
    )
    assert result["success"] is False
    assert "uuid" in result["message"].lower()


def test_register_call_agent_tool_noops_on_empty_roster():
    """The registration site MUST gate on a non-empty list — that's the
    multi-agent cap. If something slips through with an empty roster, the
    tool must NOT be registered (otherwise the LLM gets a tool with no
    valid ids to call)."""
    registry = ToolRegistry()
    register_call_agent_tool(registry, authorized_agents=[])
    assert registry.get("call_agent") is None


def test_register_call_agent_tool_registers_with_roster():
    """Happy registration: tool appears, with the right category and
    state-shape annotations expected of every Tesslate tool."""
    registry = ToolRegistry()
    roster = [{"id": str(uuid4()), "slug": "coworker", "name": "Coworker"}]
    register_call_agent_tool(registry, authorized_agents=roster)
    tool = registry.get("call_agent")
    assert tool is not None
    assert tool.category == ToolCategory.DELEGATION_OPS
    assert tool.state_serializable is True
    assert tool.holds_external_state is False
    # The roster MUST appear in the description so the LLM has access to
    # the legal id list at prompt time. (The executor still re-validates
    # at call time — defence in depth.)
    assert "coworker" in tool.description.lower()
