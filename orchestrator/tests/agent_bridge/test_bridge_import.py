"""Adapter surface imports cleanly and exposes the submodule entry points."""

from __future__ import annotations

from app.services.tesslate_agent_adapter import (
    AgentAdapterContext,
    TesslateAgentAdapter,
)


def test_adapter_context_is_frozen() -> None:
    ctx = AgentAdapterContext(project_id="p", user_id="u")
    assert ctx.project_id == "p"
    assert ctx.goal_ancestry is None


def test_adapter_wraps_submodule_agent() -> None:
    from tesslate_agent.agent.base import AbstractAgent

    adapter = TesslateAgentAdapter(system_prompt="hello", tools=None, model=None)
    assert isinstance(adapter.inner, AbstractAgent)
