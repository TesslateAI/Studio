"""Unit tests for the Phase 2 ContractGate.

Covers the three-check decision matrix (allow-list, compute-tier, spend
estimate) plus the backward-compat behavior in :class:`ToolRegistry.execute`
when no contract is in context.

The gate has no DB or Redis side effects in pure decision mode — these tests
exercise it via direct construction and an in-memory ``ToolRegistry`` fixture.
The ``contract_breaches`` increment + Redis pub/sub fan-out are covered in
the dispatcher integration tests (Wave-1B).
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.tools.contract_gate import (
    BreachKind,
    ContractGate,
    ContractGateDecision,
)
from app.agent.tools.registry import Tool, ToolCategory, ToolRegistry


# ---------------------------------------------------------------------------
# Fixtures — minimal Tool builder + a registry with one safe tool
# ---------------------------------------------------------------------------


def _make_tool(
    name: str = "noop",
    *,
    compute_tier: int = 0,
    delegates_to_model: bool = False,
) -> Tool:
    async def _executor(parameters, context):
        return {"success": True, "echo": parameters}

    return Tool(
        name=name,
        description=f"test tool {name}",
        parameters={"type": "object", "properties": {}},
        executor=_executor,
        category=ToolCategory.FILE_OPS,
        state_serializable=True,
        holds_external_state=False,
        compute_tier=compute_tier,
        delegates_to_model=delegates_to_model,
    )


@pytest.fixture
def tool() -> Tool:
    return _make_tool("read_file")


@pytest.fixture
def base_run_context() -> dict:
    return {
        "automation_run_id": "11111111-1111-1111-1111-111111111111",
        "automation_id": "22222222-2222-2222-2222-222222222222",
        "current_spend_usd": Decimal("0.10"),
    }


# ---------------------------------------------------------------------------
# Allow-list checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_not_in_allowed_tools_denies(
    tool: Tool, base_run_context: dict
) -> None:
    contract = {
        "allowed_tools": ["write_file", "web_search"],
        "max_compute_tier": 0,
    }
    gate = ContractGate(contract, base_run_context)
    decision = await gate.check(
        tool_name="read_file", tool_call_params={}, tool=tool
    )
    assert decision.allowed is False
    assert decision.breach_kind == BreachKind.TOOL_DISALLOWED
    assert "read_file" in (decision.reason or "")
    assert "allowed_tools" in (decision.reason or "")


@pytest.mark.asyncio
async def test_allowed_tools_none_means_no_enforcement(
    tool: Tool, base_run_context: dict
) -> None:
    """``allowed_tools=None`` is the "inherit project defaults" sentinel."""
    contract = {"allowed_tools": None, "max_compute_tier": 0}
    gate = ContractGate(contract, base_run_context)
    decision = await gate.check(
        tool_name="anything_at_all", tool_call_params={}, tool=tool
    )
    assert decision.allowed is True
    assert decision.breach_kind is None


@pytest.mark.asyncio
async def test_allowed_tools_empty_list_blocks_everything(
    tool: Tool, base_run_context: dict
) -> None:
    """An empty list is explicit 'deny all' — distinct from ``None``."""
    contract = {"allowed_tools": [], "max_compute_tier": 0}
    gate = ContractGate(contract, base_run_context)
    decision = await gate.check(
        tool_name="read_file", tool_call_params={}, tool=tool
    )
    assert decision.allowed is False
    assert decision.breach_kind == BreachKind.TOOL_DISALLOWED


@pytest.mark.asyncio
async def test_allowed_mcps_blocks_unlisted_mcp(
    tool: Tool, base_run_context: dict
) -> None:
    contract = {
        "allowed_tools": ["invoke_app_action"],
        "allowed_mcps": ["linear"],
        "max_compute_tier": 0,
    }
    gate = ContractGate(contract, base_run_context)
    decision = await gate.check(
        tool_name="invoke_app_action",
        tool_call_params={"mcp_name": "github"},
        tool=_make_tool("invoke_app_action"),
    )
    assert decision.allowed is False
    assert decision.breach_kind == BreachKind.MCP_DISALLOWED
    assert "github" in (decision.reason or "")


@pytest.mark.asyncio
async def test_allowed_skills_blocks_unlisted_skill(
    base_run_context: dict,
) -> None:
    contract = {
        "allowed_tools": ["load_skill"],
        "allowed_skills": ["linear-summary"],
        "max_compute_tier": 0,
    }
    gate = ContractGate(contract, base_run_context)
    decision = await gate.check(
        tool_name="load_skill",
        tool_call_params={"skill_name": "github-pr-review"},
        tool=_make_tool("load_skill"),
    )
    assert decision.allowed is False
    assert decision.breach_kind == BreachKind.SKILL_DISALLOWED
    assert "github-pr-review" in (decision.reason or "")


# ---------------------------------------------------------------------------
# Compute-tier check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier_too_high_denies(base_run_context: dict) -> None:
    tool_t2 = _make_tool("heavy_build", compute_tier=2)
    contract = {
        "allowed_tools": ["heavy_build"],
        "max_compute_tier": 1,
    }
    gate = ContractGate(contract, base_run_context)
    decision = await gate.check(
        tool_name="heavy_build", tool_call_params={}, tool=tool_t2
    )
    assert decision.allowed is False
    assert decision.breach_kind == BreachKind.TIER_TOO_HIGH
    assert "tier 2" in (decision.reason or "")
    assert "max_compute_tier=1" in (decision.reason or "")


@pytest.mark.asyncio
async def test_tier_within_cap_passes(base_run_context: dict) -> None:
    tool_t1 = _make_tool("medium_tool", compute_tier=1)
    contract = {
        "allowed_tools": ["medium_tool"],
        "max_compute_tier": 2,
    }
    gate = ContractGate(contract, base_run_context)
    decision = await gate.check(
        tool_name="medium_tool", tool_call_params={}, tool=tool_t1
    )
    assert decision.allowed is True


# ---------------------------------------------------------------------------
# Spend-estimate check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spend_estimate_exceeds_remaining_budget_denies(
    tool: Tool, base_run_context: dict
) -> None:
    contract = {
        "allowed_tools": ["read_file"],
        "max_compute_tier": 0,
        "max_spend_per_run_usd": Decimal("0.20"),
    }
    # current_spend_usd=0.10, max_per_run=0.20, remaining=0.10
    # estimator returns 0.50 → exceeds remaining → deny
    base_run_context["current_spend_usd"] = Decimal("0.10")
    gate = ContractGate(contract, base_run_context)

    with patch(
        "app.services.apps.billing_dispatcher.estimate",
        new=AsyncMock(return_value=Decimal("0.50")),
        create=True,
    ):
        decision = await gate.check(
            tool_name="read_file", tool_call_params={}, tool=tool
        )

    assert decision.allowed is False
    assert decision.breach_kind == BreachKind.BUDGET_EXCEEDED
    assert decision.estimate_usd == Decimal("0.50")
    assert "0.50" in (decision.reason or "")


@pytest.mark.asyncio
async def test_spend_estimate_within_budget_passes(
    tool: Tool, base_run_context: dict
) -> None:
    contract = {
        "allowed_tools": ["read_file"],
        "max_compute_tier": 0,
        "max_spend_per_run_usd": Decimal("1.00"),
    }
    base_run_context["current_spend_usd"] = Decimal("0.10")
    gate = ContractGate(contract, base_run_context)

    with patch(
        "app.services.apps.billing_dispatcher.estimate",
        new=AsyncMock(return_value=Decimal("0.05")),
        create=True,
    ):
        decision = await gate.check(
            tool_name="read_file", tool_call_params={}, tool=tool
        )

    assert decision.allowed is True


@pytest.mark.asyncio
async def test_delegates_to_model_skips_spend_estimate(
    base_run_context: dict,
) -> None:
    """A tool that wraps a model call MUST skip the per-tool estimate;
    its spend is captured by the LiteLLM key, not the estimator."""
    model_tool = _make_tool("summarize_text", delegates_to_model=True)
    contract = {
        "allowed_tools": ["summarize_text"],
        "max_compute_tier": 0,
        "max_spend_per_run_usd": Decimal("0.01"),
    }
    base_run_context["current_spend_usd"] = Decimal("0.005")

    gate = ContractGate(contract, base_run_context)

    # Estimator returns a huge value — gate must not call it.
    estimator = AsyncMock(return_value=Decimal("999.99"))
    with patch(
        "app.services.apps.billing_dispatcher.estimate",
        new=estimator,
        create=True,
    ):
        decision = await gate.check(
            tool_name="summarize_text", tool_call_params={}, tool=model_tool
        )

    assert decision.allowed is True
    estimator.assert_not_called()


@pytest.mark.asyncio
async def test_no_max_spend_per_run_skips_estimate(
    tool: Tool, base_run_context: dict
) -> None:
    """Without ``max_spend_per_run_usd`` the gate has no per-call budget
    to compare against — only the daily cap applies (enforced elsewhere)."""
    contract = {"allowed_tools": ["read_file"], "max_compute_tier": 0}
    gate = ContractGate(contract, base_run_context)
    decision = await gate.check(
        tool_name="read_file", tool_call_params={}, tool=tool
    )
    assert decision.allowed is True


# ---------------------------------------------------------------------------
# Decision dataclass invariants
# ---------------------------------------------------------------------------


def test_decision_is_frozen() -> None:
    decision = ContractGateDecision(allowed=True)
    with pytest.raises(Exception):
        # frozen dataclass — assignment must raise FrozenInstanceError
        decision.allowed = False  # type: ignore[misc]


def test_default_estimate_is_zero() -> None:
    decision = ContractGateDecision(allowed=True)
    assert decision.estimate_usd == Decimal(0)


# ---------------------------------------------------------------------------
# Registry integration — backward-compat (no contract → no gate)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_skips_contract_gate_when_no_contract(
    tool: Tool,
) -> None:
    """Existing chat sessions never set ``context['contract']``; the registry
    must not invoke the gate or import any of its DB-touching helpers."""
    registry = ToolRegistry()
    registry.register(tool)

    # No 'contract' key at all — exact backward-compat shape.
    context = {"chat_id": "chat-x", "edit_mode": "yolo"}
    result = await registry.execute("read_file", {}, context)
    assert result["success"] is True
    assert result["tool"] == "read_file"
    assert "approval_required" not in result


@pytest.mark.asyncio
async def test_registry_skips_contract_gate_when_contract_is_none(
    tool: Tool,
) -> None:
    """The worker always plumbs ``context['contract']`` (None for non-
    automation invocations). A None value is the documented backward-
    compat sentinel — gate must be skipped."""
    registry = ToolRegistry()
    registry.register(tool)

    context = {
        "chat_id": "chat-x",
        "edit_mode": "yolo",
        "automation_run_id": None,
        "automation_id": None,
        "contract": None,
    }
    result = await registry.execute("read_file", {}, context)
    assert result["success"] is True


@pytest.mark.asyncio
async def test_registry_invokes_contract_gate_when_contract_present(
    tool: Tool,
) -> None:
    """When a contract IS present and the tool is not allowed, the registry
    must surface ``approval_required=True`` (default ``on_breach``) with
    the contract_breach metadata attached."""
    registry = ToolRegistry()
    registry.register(tool)

    context = {
        "chat_id": "chat-x",
        "edit_mode": "yolo",
        "automation_run_id": None,  # disables DB increment
        "contract": {
            "allowed_tools": ["write_file"],  # read_file deliberately omitted
            "max_compute_tier": 0,
            "on_breach": "pause_for_approval",
        },
    }
    result = await registry.execute("read_file", {}, context)
    assert result.get("approval_required") is True
    assert result["tool"] == "read_file"
    breach = result.get("contract_breach", {})
    assert breach.get("kind") == BreachKind.TOOL_DISALLOWED


@pytest.mark.asyncio
async def test_registry_hard_stop_returns_failure(tool: Tool) -> None:
    """``on_breach='hard_stop'`` must NOT raise an approval — it returns
    a plain failure with the breach metadata so the run terminates."""
    registry = ToolRegistry()
    registry.register(tool)

    context = {
        "chat_id": "chat-x",
        "edit_mode": "yolo",
        "automation_run_id": None,
        "contract": {
            "allowed_tools": [],  # deny all
            "max_compute_tier": 0,
            "on_breach": "hard_stop",
        },
    }
    result = await registry.execute("read_file", {}, context)
    assert result["success"] is False
    assert "approval_required" not in result
    breach = result.get("contract_breach", {})
    assert breach.get("on_breach") == "hard_stop"
    assert breach.get("kind") == BreachKind.TOOL_DISALLOWED
