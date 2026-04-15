"""
Tests for delegation_ops tools.

These tests exercise the subagent registry and the five delegation tool
executors against a fake agent class that yields a deterministic event
sequence. The fake agent is monkeypatched over the real ``TesslateAgent``
symbol that the delegation runner imports lazily.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[4]
if str(_ORCHESTRATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_ORCHESTRATOR_ROOT))

from app.agent.tools.delegation_ops import (  # noqa: E402
    MAX_SUBAGENT_DEPTH,
    SUBAGENT_REGISTRY,
    SubagentRecord,
    SubagentRegistry,
    close_agent_executor,
    list_agents_executor,
    register_delegation_ops_tools,
    send_message_to_agent_executor,
    task_executor,
    wait_agent_executor,
)
from app.agent.tools.delegation_ops.agent_registry import (  # noqa: E402
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
)
from app.agent.tools.registry import (  # noqa: E402
    ToolCategory,
    ToolRegistry,
    get_tool_registry,
)

# ---------------------------------------------------------------------------
# Fake agent and adapter
# ---------------------------------------------------------------------------


class FakeModelAdapter:
    """Minimal adapter stand-in — only the attributes used by the runner."""

    def __init__(self, model_name: str = "fake/model") -> None:
        self.model_name = model_name
        self.thinking_effort = ""


class FakeAgent:
    """Deterministic replacement for TesslateAgent.

    Yields an ``agent_step`` (with a tool_call), a ``tool_call`` event,
    then a ``complete`` event. An optional artificial delay and explicit
    failure mode let individual tests steer the behaviour.
    """

    def __init__(
        self,
        system_prompt: str,
        tools: ToolRegistry | None = None,
        model: FakeModelAdapter | None = None,
    ) -> None:
        self.system_prompt = system_prompt
        self.tools = tools
        self.model = model

    # Class-level knobs so individual tests can tweak behaviour without
    # re-monkeypatching the import.
    delay_s: float = 0.0
    should_raise: bool = False
    final_response: str = "fake subagent finished cleanly"

    async def run(self, prompt: str, context: dict[str, Any]):
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.should_raise:
            raise RuntimeError("fake boom")

        yield {
            "type": "agent_step",
            "data": {
                "iteration": 1,
                "tool_calls": [{"name": "read_file", "parameters": {"file_path": "a.py"}}],
                "tool_results": [{"success": True}],
                "response_text": "looking at a.py",
            },
        }
        yield {
            "type": "tool_call",
            "data": {
                "iteration": 1,
                "index": 0,
                "total": 1,
                "name": "read_file",
                "parameters": {"file_path": "a.py"},
                "result": {"success": True, "message": "ok"},
            },
        }
        yield {
            "type": "complete",
            "data": {
                "success": True,
                "final_response": self.final_response,
                "iterations": 1,
                "tool_calls_made": 1,
                "completion_reason": "no_more_actions",
            },
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    SUBAGENT_REGISTRY.clear()
    yield
    SUBAGENT_REGISTRY.clear()


@pytest.fixture
def patch_fake_agent(monkeypatch: pytest.MonkeyPatch):
    """Replace the real TesslateAgent import target with FakeAgent."""
    import app.agent.tools.delegation_ops.task_tool as _task_module

    monkeypatch.setattr(_task_module, "TesslateAgent", FakeAgent)
    # Also patch the submodule source so the late-import path (if any) picks up FakeAgent.
    import tesslate_agent.agent.tesslate_agent as _ta_mod

    monkeypatch.setattr(_ta_mod, "TesslateAgent", FakeAgent)
    yield FakeAgent
    # Reset class-level knobs so tests stay isolated.
    FakeAgent.delay_s = 0.0
    FakeAgent.should_raise = False
    FakeAgent.final_response = "fake subagent finished cleanly"


@pytest.fixture
def parent_context() -> dict[str, Any]:
    return {
        "agent_id": "parent-agent-xyz",
        "subagent_depth": 0,
        "model_adapter": FakeModelAdapter(),
        "user_id": None,
        "db": None,
        "project_id": "proj-test",
        "project_slug": "proj-test",
    }


# ---------------------------------------------------------------------------
# 1. task wait=False returns immediately with agent_id + running status
# ---------------------------------------------------------------------------


async def test_task_wait_false_returns_immediately(patch_fake_agent, parent_context):
    FakeAgent.delay_s = 0.5  # ensure still running when executor returns
    result = await task_executor(
        {"role": "explore", "prompt": "map foo()", "wait": False},
        parent_context,
    )
    assert result["success"] is True
    assert result["role"] == "explore"
    assert result["status"] == STATUS_RUNNING
    agent_id = result["agent_id"]
    assert isinstance(agent_id, str) and agent_id

    record = SUBAGENT_REGISTRY.get(agent_id)
    assert record is not None
    assert record.depth == 1
    assert record.parent_agent_id == "parent-agent-xyz"

    # Cleanup — wait for the task so other tests don't see it pending.
    await wait_agent_executor({"agent_id": agent_id, "timeout_ms": 5000}, {})


# ---------------------------------------------------------------------------
# 2. task wait=True returns final response + trajectory
# ---------------------------------------------------------------------------


async def test_task_wait_true_returns_final_response_and_trajectory(
    patch_fake_agent, parent_context
):
    FakeAgent.final_response = "done exploring"
    result = await task_executor(
        {"role": "explore", "prompt": "scan", "wait": True},
        parent_context,
    )
    assert result["success"] is True
    assert result["status"] == STATUS_COMPLETED
    assert result["final_response"] == "done exploring"
    traj = result["trajectory"]
    assert isinstance(traj, dict)
    assert traj.get("schema_version", "").startswith("ATIF")
    # Round-trip through json to prove it is serializable.
    assert json.dumps(traj)


# ---------------------------------------------------------------------------
# 3. Depth cap enforced
# ---------------------------------------------------------------------------


async def test_depth_cap_enforced(patch_fake_agent):
    ctx = {
        "agent_id": "deep-parent",
        "subagent_depth": MAX_SUBAGENT_DEPTH,
        "model_adapter": FakeModelAdapter(),
    }
    result = await task_executor({"role": "cap", "prompt": "should fail"}, ctx)
    assert result["success"] is False
    assert "maximum subagent depth" in result["message"]


# ---------------------------------------------------------------------------
# 4. Recursion guard — delegation tools are stripped from default scope
# ---------------------------------------------------------------------------


async def test_recursion_guard_strips_delegation_tools(patch_fake_agent, parent_context):
    # Pre-populate the global registry with the delegation tools so
    # default-scope resolution has something to strip.
    global_registry = get_tool_registry()
    register_delegation_ops_tools(global_registry)

    captured: dict[str, Any] = {}

    class CapturingAgent(FakeAgent):
        def __init__(self, system_prompt, tools=None, model=None):
            super().__init__(system_prompt, tools, model)
            captured["tool_names"] = list(tools._tools.keys()) if tools else []

    import app.agent.tools.delegation_ops.task_tool as _task_module

    # Re-patch to our capturing subclass for this one test.
    _task_module.TesslateAgent = CapturingAgent
    try:
        result = await task_executor(
            {"role": "check", "prompt": "scope check", "wait": True},
            parent_context,
        )
        assert result["success"] is True
    finally:
        _task_module.TesslateAgent = FakeAgent

    tool_names = captured.get("tool_names") or []
    for banned in ("task", "wait_agent", "send_message_to_agent", "close_agent", "list_agents"):
        assert banned not in tool_names, f"{banned} leaked into subagent scope"


# ---------------------------------------------------------------------------
# 5. wait_agent on unknown agent_id → structured error
# ---------------------------------------------------------------------------


async def test_wait_agent_unknown_id():
    result = await wait_agent_executor({"agent_id": "does-not-exist"}, {})
    assert result["success"] is False
    assert "unknown" in result["message"].lower()


# ---------------------------------------------------------------------------
# 6. wait_agent blocks until complete
# ---------------------------------------------------------------------------


async def test_wait_agent_blocks_until_complete(patch_fake_agent, parent_context):
    FakeAgent.delay_s = 0.05
    spawn = await task_executor(
        {"role": "slow", "prompt": "wait for me", "wait": False},
        parent_context,
    )
    agent_id = spawn["agent_id"]
    result = await wait_agent_executor({"agent_id": agent_id, "timeout_ms": 5000}, {})
    assert result["success"] is True
    assert result["status"] == STATUS_COMPLETED


# ---------------------------------------------------------------------------
# 7. wait_agent timeout shorter than run → still_running
# ---------------------------------------------------------------------------


async def test_wait_agent_short_timeout_returns_still_running(patch_fake_agent, parent_context):
    FakeAgent.delay_s = 1.0
    spawn = await task_executor(
        {"role": "slow", "prompt": "long job", "wait": False},
        parent_context,
    )
    agent_id = spawn["agent_id"]
    result = await wait_agent_executor({"agent_id": agent_id, "timeout_ms": 20}, {})
    assert result["success"] is True
    assert result["status"] == "still_running"

    # Clean up — let the task finish before moving on.
    await wait_agent_executor({"agent_id": agent_id, "timeout_ms": 5000}, {})


# ---------------------------------------------------------------------------
# 8. send_message_to_agent enqueues and errors on non-running
# ---------------------------------------------------------------------------


async def test_send_message_to_agent(patch_fake_agent, parent_context):
    FakeAgent.delay_s = 0.2
    spawn = await task_executor(
        {"role": "chatty", "prompt": "need messages", "wait": False},
        parent_context,
    )
    agent_id = spawn["agent_id"]

    msg_result = await send_message_to_agent_executor(
        {"agent_id": agent_id, "message": "hello"}, {}
    )
    assert msg_result["success"] is True
    assert msg_result["queued"] is True
    assert msg_result["queue_depth"] == 1

    msg_result_2 = await send_message_to_agent_executor(
        {"agent_id": agent_id, "message": "world"}, {}
    )
    assert msg_result_2["queue_depth"] == 2

    # Drain before the runner does to assert the record actually holds them.
    record = SUBAGENT_REGISTRY.get(agent_id)
    assert record is not None

    await wait_agent_executor({"agent_id": agent_id, "timeout_ms": 5000}, {})

    # After completion, sending to it should fail.
    fail_result = await send_message_to_agent_executor(
        {"agent_id": agent_id, "message": "late"}, {}
    )
    assert fail_result["success"] is False


# ---------------------------------------------------------------------------
# 9. close_agent cancels a running subagent and is idempotent
# ---------------------------------------------------------------------------


async def test_close_agent_cancels_and_is_idempotent(patch_fake_agent, parent_context):
    FakeAgent.delay_s = 5.0  # well above the close timeout
    spawn = await task_executor(
        {"role": "stuck", "prompt": "will be closed", "wait": False},
        parent_context,
    )
    agent_id = spawn["agent_id"]

    first = await close_agent_executor({"agent_id": agent_id}, {})
    assert first["success"] is True
    assert first["status"] == STATUS_CANCELLED

    second = await close_agent_executor({"agent_id": agent_id}, {})
    assert second["success"] is True
    assert second["status"] == STATUS_CANCELLED


# ---------------------------------------------------------------------------
# 10. list_agents filtering
# ---------------------------------------------------------------------------


async def test_list_agents_filters(patch_fake_agent, parent_context):
    # Spawn two to completion, one that stays running.
    FakeAgent.delay_s = 0.0
    r1 = await task_executor({"role": "one", "prompt": "a", "wait": True}, parent_context)
    r2 = await task_executor({"role": "two", "prompt": "b", "wait": True}, parent_context)
    assert r1["status"] == STATUS_COMPLETED
    assert r2["status"] == STATUS_COMPLETED

    FakeAgent.delay_s = 2.0
    r3 = await task_executor({"role": "three", "prompt": "c", "wait": False}, parent_context)
    # Yield control so the background task gets a chance to reach its
    # ``mark_running`` checkpoint before we inspect the registry.
    await asyncio.sleep(0.05)

    listing = await list_agents_executor({}, {})
    assert listing["success"] is True
    assert len(listing["agents"]) == 3

    running_only = await list_agents_executor({"status": STATUS_RUNNING}, {})
    assert all(a["status"] == STATUS_RUNNING for a in running_only["agents"])
    assert len(running_only["agents"]) == 1

    completed_only = await list_agents_executor({"status": STATUS_COMPLETED}, {})
    assert len(completed_only["agents"]) == 2

    parent_filter = await list_agents_executor({"parent_agent_id": "parent-agent-xyz"}, {})
    assert len(parent_filter["agents"]) == 3

    empty_filter = await list_agents_executor({"parent_agent_id": "other-parent"}, {})
    assert empty_filter["agents"] == []

    # Clean up the still-running task.
    await close_agent_executor({"agent_id": r3["agent_id"]}, {})


# ---------------------------------------------------------------------------
# 11. Exception in child → record status becomes failed
# ---------------------------------------------------------------------------


async def test_child_exception_marks_record_failed(patch_fake_agent, parent_context):
    FakeAgent.should_raise = True
    result = await task_executor(
        {"role": "boom", "prompt": "explode", "wait": True}, parent_context
    )
    assert result["status"] == STATUS_FAILED
    record = SUBAGENT_REGISTRY.get(result["agent_id"])
    assert record is not None
    assert record.error is not None
    assert "fake boom" in record.error


# ---------------------------------------------------------------------------
# 12. Events buffered in order
# ---------------------------------------------------------------------------


async def test_events_buffered_in_order(patch_fake_agent, parent_context):
    result = await task_executor({"role": "events", "prompt": "go", "wait": True}, parent_context)
    agent_id = result["agent_id"]
    record = SUBAGENT_REGISTRY.get(agent_id)
    assert record is not None
    types = [e.get("type") for e in record.events]
    assert types == ["agent_step", "tool_call", "complete"]


# ---------------------------------------------------------------------------
# 13. Trajectory attached and JSON-serializable
# ---------------------------------------------------------------------------


async def test_trajectory_is_json_serializable(patch_fake_agent, parent_context):
    result = await task_executor({"role": "trace", "prompt": "go", "wait": True}, parent_context)
    record = SUBAGENT_REGISTRY.get(result["agent_id"])
    assert record is not None
    assert isinstance(record.trajectory, dict)
    blob = json.dumps(record.trajectory)
    assert '"ATIF' in blob


# ---------------------------------------------------------------------------
# Bonus: the registration helper installs all 5 tools under DELEGATION_OPS
# ---------------------------------------------------------------------------


def test_register_delegation_ops_tools():
    reg = ToolRegistry()
    register_delegation_ops_tools(reg)
    names = set(reg._tools.keys())
    assert names == {
        "task",
        "wait_agent",
        "send_message_to_agent",
        "close_agent",
        "list_agents",
    }
    for name in names:
        assert reg.get(name).category == ToolCategory.DELEGATION_OPS


def test_subagent_registry_dataclass_roundtrip():
    from datetime import UTC, datetime

    rec = SubagentRecord(
        agent_id="a1",
        role="demo",
        status=STATUS_RUNNING,
        spawned_at=datetime.now(UTC),
        task_text="do things",
        model_name="fake",
        depth=1,
    )
    snap = rec.snapshot()
    # Must be JSON-serializable.
    json.dumps(snap)
    assert snap["agent_id"] == "a1"
    assert snap["depth"] == 1
    assert snap["status"] == STATUS_RUNNING


def test_subagent_registry_singleton_is_a_registry():
    assert isinstance(SUBAGENT_REGISTRY, SubagentRegistry)
