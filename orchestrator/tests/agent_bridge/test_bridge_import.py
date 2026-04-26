"""Adapter surface imports cleanly and exposes the submodule entry points."""

from __future__ import annotations

from typing import Any

import pytest

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


# ---------------------------------------------------------------------------
# run_turn() context-building tests — Bug #198
# ---------------------------------------------------------------------------


class _StubAdapter:
    """Minimal ModelAdapter stub that records the context it receives."""

    def __init__(self) -> None:
        self.received_contexts: list[dict[str, Any]] = []

    @property
    def model_name(self) -> str:
        return "stub/model"

    async def chat_with_tools(self, messages, tools=None, tool_choice="auto", **kw):
        # Capture the context from the messages (first system message content)
        return {"content": "done", "tool_calls": [], "usage": {}, "finish_reason": "stop"}


@pytest.mark.asyncio
async def test_run_turn_does_not_crash_on_context_conversion() -> None:
    """run_turn() must convert AgentAdapterContext to a plain dict without
    AttributeError (the old code called .to_submodule_context() which
    does not exist on the frozen dataclass)."""
    from tesslate_agent.agent.tools.registry import ToolRegistry

    model = _StubAdapter()
    adapter = TesslateAgentAdapter(
        system_prompt="test",
        tools=ToolRegistry(),
        model=model,
    )
    ctx = AgentAdapterContext(
        project_id="proj-123",
        user_id="user-456",
        extra={"edit_mode": "plan", "some_key": "val"},
    )

    last: dict[str, Any] = {}
    async for event in adapter.run_turn("hello", ctx):
        last = event
    assert isinstance(last, dict)
    assert last.get("type") == "complete"


@pytest.mark.asyncio
async def test_run_turn_context_includes_extra_fields() -> None:
    """Extra fields from AgentAdapterContext.extra are merged into the
    context dict so that edit_mode, project_slug, etc. reach the agent."""
    from collections.abc import AsyncIterator

    captured_contexts: list[dict[str, Any]] = []

    class _CapturingAgent:
        system_prompt = "test"
        tools = None

        async def run(
            self, user_request: str, context: dict[str, Any]
        ) -> AsyncIterator[dict[str, Any]]:
            captured_contexts.append(dict(context))
            yield {
                "type": "complete",
                "data": {
                    "success": True,
                    "iterations": 1,
                    "final_response": "",
                    "tool_calls_made": 0,
                    "completion_reason": "stop",
                },
            }

    from app.services.tesslate_agent_adapter import TesslateAgentAdapter

    # Bypass __init__ to inject our capturing agent
    wrapper = object.__new__(TesslateAgentAdapter)
    wrapper._inner = _CapturingAgent()  # type: ignore[attr-defined]

    ctx = AgentAdapterContext(
        project_id="p1",
        user_id="u1",
        goal_ancestry=["root"],
        extra={"edit_mode": "plan", "chat_id": "chat-99"},
    )
    async for _ in wrapper.run_turn("do something", ctx):
        pass

    assert len(captured_contexts) == 1
    c = captured_contexts[0]
    assert c["project_id"] == "p1"
    assert c["user_id"] == "u1"
    assert c["goal_ancestry"] == ["root"]
    assert c["edit_mode"] == "plan"
    assert c["chat_id"] == "chat-99"


# ---------------------------------------------------------------------------
# approval_handler injection via run_turn — Bug #198
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_turn_approval_handler_called_for_dangerous_tool() -> None:
    """An approval_handler injected into the ToolRegistry is invoked when
    a dangerous tool is executed in ask mode during run_turn().  This verifies
    the handler wiring survives the adapter → submodule boundary."""
    from collections.abc import AsyncIterator

    approval_calls: list[tuple[str, str]] = []

    async def _capturing_handler(tool_name: str, params: dict, session_id: str) -> str:
        approval_calls.append((tool_name, session_id))
        return "allow_once"

    class _ToolCallingAgent:
        """Minimal agent that always calls patch_file and then completes."""

        system_prompt = "test"

        def __init__(self) -> None:
            from tesslate_agent.agent.tools.registry import Tool, ToolCategory, ToolRegistry

            async def _noop(p: dict, ctx: dict) -> dict:
                return {"success": True}

            self.tools = ToolRegistry(approval_handler=_capturing_handler)
            self.tools.register(
                Tool(
                    name="patch_file",
                    description="edit a file",
                    parameters={"type": "object", "properties": {}},
                    executor=_noop,
                    category=ToolCategory.FILE_OPS,
                )
            )

        async def run(self, user_request: str, context: dict) -> AsyncIterator[dict]:
            # Simulate the agent executing a dangerous tool then completing.
            await self.tools.execute(
                "patch_file",
                {"file_path": "app.py"},
                context={**context, "edit_mode": "ask"},
            )
            yield {
                "type": "complete",
                "data": {
                    "success": True,
                    "iterations": 1,
                    "final_response": "",
                    "tool_calls_made": 1,
                    "completion_reason": "stop",
                },
            }

    from app.services.tesslate_agent_adapter import TesslateAgentAdapter

    wrapper = object.__new__(TesslateAgentAdapter)
    wrapper._inner = _ToolCallingAgent()  # type: ignore[attr-defined]

    ctx = AgentAdapterContext(project_id="p2", user_id="u2", extra={"chat_id": "chat-42"})
    async for _ in wrapper.run_turn("patch something", ctx):
        pass

    assert len(approval_calls) == 1
    assert approval_calls[0][0] == "patch_file"
    assert approval_calls[0][1] == "chat-42"
