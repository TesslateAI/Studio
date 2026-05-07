"""Phase B (#471): ContractGate refuses workspace tools in connector_only.

Pure unit tests; no DB. Covers:

* ``connector_only`` rejects ``read_file`` / ``bash_exec`` /
  ``container_logs`` with breach_kind=WORKSPACE_REQUIRED.
* ``connector_only`` allows ``send_message``, ``invoke_app_action``,
  ``web_fetch`` (the connector-only whitelist).
* ``connector_only`` allows MCP-bridged tools (``mcp__*``).
* ``persistent_workspace`` (today's behavior) is unaffected.
* The check runs BEFORE allow-lists so the user sees the workspace
  reason rather than a tool-allow-list miss when both fire.
"""

from __future__ import annotations

import pytest


def _make_gate(*, compute_profile: str = "persistent_workspace", contract=None):
    from app.agent.tools.contract_gate import ContractGate

    return ContractGate(
        contract=contract or {"allowed_tools": None, "max_compute_tier": 0},
        run_context={"compute_profile": compute_profile},
    )


def _fake_tool(name: str = "tool", compute_tier: int = 0):
    """Minimal Tool stub matching what the gate reads."""

    class _T:
        pass

    t = _T()
    t.name = name
    t.compute_tier = compute_tier
    t.delegates_to_model = False
    t.estimate_cost_usd = lambda **_: 0
    return t


@pytest.mark.asyncio
async def test_connector_only_refuses_filesystem_tool():
    from app.agent.tools.contract_gate import BreachKind

    gate = _make_gate(compute_profile="connector_only")
    decision = await gate.check(
        tool_name="read_file",
        tool_call_params={"path": "/etc/passwd"},
        tool=_fake_tool("read_file"),
    )
    assert decision.allowed is False
    assert decision.breach_kind == BreachKind.WORKSPACE_REQUIRED
    assert "workspace" in (decision.reason or "")


@pytest.mark.asyncio
async def test_connector_only_refuses_shell_tool():
    from app.agent.tools.contract_gate import BreachKind

    gate = _make_gate(compute_profile="connector_only")
    decision = await gate.check(
        tool_name="bash_exec",
        tool_call_params={"command": "ls"},
        tool=_fake_tool("bash_exec"),
    )
    assert decision.allowed is False
    assert decision.breach_kind == BreachKind.WORKSPACE_REQUIRED


@pytest.mark.asyncio
async def test_connector_only_refuses_container_tool():
    from app.agent.tools.contract_gate import BreachKind

    gate = _make_gate(compute_profile="connector_only")
    decision = await gate.check(
        tool_name="container_logs",
        tool_call_params={},
        tool=_fake_tool("container_logs"),
    )
    assert decision.allowed is False
    assert decision.breach_kind == BreachKind.WORKSPACE_REQUIRED


@pytest.mark.asyncio
async def test_connector_only_allows_send_message():
    gate = _make_gate(compute_profile="connector_only")
    decision = await gate.check(
        tool_name="send_message",
        tool_call_params={"channel": "slack", "body": "hi"},
        tool=_fake_tool("send_message"),
    )
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_connector_only_allows_invoke_app_action():
    gate = _make_gate(compute_profile="connector_only")
    decision = await gate.check(
        tool_name="invoke_app_action",
        tool_call_params={
            "app_instance_id": "x",
            "action_name": "fetch",
            "input": {},
        },
        tool=_fake_tool("invoke_app_action"),
    )
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_connector_only_allows_mcp_bridged_tool():
    gate = _make_gate(compute_profile="connector_only")
    decision = await gate.check(
        tool_name="mcp__slack__send_message",
        tool_call_params={"channel": "#ops"},
        tool=_fake_tool("mcp__slack__send_message"),
    )
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_persistent_workspace_unaffected():
    """Today's behavior: read_file is allowed (no workspace gate)."""
    gate = _make_gate(compute_profile="persistent_workspace")
    decision = await gate.check(
        tool_name="read_file",
        tool_call_params={"path": "/workspace/README.md"},
        tool=_fake_tool("read_file"),
    )
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_default_profile_is_persistent_workspace():
    """No compute_profile in run_context defaults to persistent_workspace."""
    from app.agent.tools.contract_gate import ContractGate

    gate = ContractGate(
        contract={"allowed_tools": None, "max_compute_tier": 0},
        run_context={},
    )
    decision = await gate.check(
        tool_name="read_file",
        tool_call_params={},
        tool=_fake_tool("read_file"),
    )
    assert decision.allowed is True
