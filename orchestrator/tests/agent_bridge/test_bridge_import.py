"""Bridge surface imports cleanly and exposes the submodule entry points."""

from __future__ import annotations

from app.services.tesslate_agent_bridge import (
    BridgeContext,
    TesslateAgentBridge,
)


def test_bridge_context_is_frozen() -> None:
    ctx = BridgeContext(project_id="p", user_id="u")
    assert ctx.project_id == "p"
    assert ctx.goal_ancestry is None


def test_bridge_wraps_submodule_agent() -> None:
    from tesslate_agent.agent.base import AbstractAgent

    bridge = TesslateAgentBridge(system_prompt="hello", tools=None, model=None)
    assert isinstance(bridge.inner, AbstractAgent)
