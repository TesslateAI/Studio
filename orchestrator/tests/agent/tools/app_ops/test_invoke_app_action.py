"""Unit tests for the ``invoke_app_action`` agent tool.

Verifies:

* The tool is registered + discoverable through the global ``ToolRegistry``
  with the right scope, dangerous-tool membership, and state annotations.
* A successful dispatch surfaces the typed dispatcher result as a clean
  ``{success: True, ok: True, output, artifact_ids, ...}`` payload.
* A typed ``ActionDispatchError`` is converted to a structured
  ``{success: False, ok: False, error, error_message}`` result rather than
  propagating as an exception (Phase 1 contract — the agent must always
  receive a parseable tool result, never a stack trace).
* Input validation (missing args, bad UUID, non-dict input) returns a
  structured error and never reaches the dispatcher.

Reference: Phase 1 §"App actions" + §"invoke_app_action" in
``/Users/smirk/.claude/plans/ultrathink-i-want-to-glittery-pond.md``.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

from app.agent.tools.app_ops.invoke_app_action import (
    invoke_app_action_executor,
    register_invoke_app_action_tool,
)
from app.agent.tools.registry import ToolCategory, ToolRegistry, get_tool_registry


# ---------------------------------------------------------------------------
# Registry / annotation tests
# ---------------------------------------------------------------------------


def test_invoke_app_action_is_registered_globally():
    """The tool MUST be discoverable via the global registry."""
    registry = get_tool_registry()
    tool = registry.get("invoke_app_action")
    assert tool is not None, (
        "invoke_app_action was not registered globally — check "
        "_register_all_tools in app/agent/tools/registry.py."
    )
    assert tool.name == "invoke_app_action"
    assert tool.category == ToolCategory.PROJECT


def test_invoke_app_action_has_required_state_annotations():
    """Wave 1B annotation invariants must hold for this tool."""
    registry = get_tool_registry()
    tool = registry.get("invoke_app_action")
    assert tool is not None
    # JSON-clean inputs + JSON-clean outputs — checkpointable.
    assert tool.state_serializable is True
    # One-shot dispatch; no persistent stream/socket/PTY across the call.
    assert tool.holds_external_state is False


def test_invoke_app_action_requires_app_invoke_scope():
    """API key scope mapping wires invoke_app_action -> app.invoke."""
    registry = get_tool_registry()
    assert registry.TOOL_REQUIRED_SCOPES.get("invoke_app_action") == "app.invoke"


def test_invoke_app_action_is_in_dangerous_tools():
    """Dangerous-tool membership gates plan-mode + ask-mode approval."""
    registry = get_tool_registry()
    assert "invoke_app_action" in registry.DANGEROUS_TOOLS


def test_register_helper_is_idempotent_against_fresh_registry():
    """The helper must register the tool on a fresh registry without error."""
    fresh = ToolRegistry()
    register_invoke_app_action_tool(fresh)
    tool = fresh.get("invoke_app_action")
    assert tool is not None
    assert tool.parameters["required"] == ["app_instance_id", "action_name"]


# ---------------------------------------------------------------------------
# Executor: success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_success_surfaces_dispatcher_result():
    """On success the tool result mirrors the dispatcher's typed payload."""
    from app.services.apps.action_dispatcher import ActionDispatchResult

    instance_id = uuid4()
    artifact_id = uuid4()
    fake_result = ActionDispatchResult(
        output={"summary": "ok", "rows_processed": 5},
        artifacts=[artifact_id],
        spend_usd=Decimal("0.01"),
        duration_seconds=0.1234,
        error=None,
    )

    db = AsyncMock()
    context = {"db": db}
    params = {
        "app_instance_id": str(instance_id),
        "action_name": "summarize_pipeline",
        "input": {"pipeline_id": "pl-42"},
    }

    with patch(
        "app.services.apps.action_dispatcher.dispatch_app_action",
        AsyncMock(return_value=fake_result),
    ) as patched:
        result = await invoke_app_action_executor(params, context)

    assert result["success"] is True
    assert result["ok"] is True
    assert result["output"] == {"summary": "ok", "rows_processed": 5}
    assert result["artifact_ids"] == [str(artifact_id)]
    assert result["spend_usd"] == "0.01"
    assert result["duration_seconds"] == pytest.approx(0.1234, rel=1e-3)

    patched.assert_awaited_once()
    kwargs = patched.await_args.kwargs
    assert kwargs["app_instance_id"] == instance_id
    assert kwargs["action_name"] == "summarize_pipeline"
    assert kwargs["input"] == {"pipeline_id": "pl-42"}
    # No automation_run_id in the context → run_id forwarded as None.
    assert kwargs["run_id"] is None
    assert kwargs["invocation_subject_id"] is None


@pytest.mark.asyncio
async def test_executor_forwards_automation_run_id():
    """When the context carries automation_run_id we propagate it as a UUID."""
    from app.services.apps.action_dispatcher import ActionDispatchResult

    instance_id = uuid4()
    run_id = uuid4()
    fake_result = ActionDispatchResult(output={}, artifacts=[], spend_usd=Decimal("0"))

    db = AsyncMock()
    context = {"db": db, "automation_run_id": str(run_id)}
    params = {
        "app_instance_id": str(instance_id),
        "action_name": "noop",
    }

    with patch(
        "app.services.apps.action_dispatcher.dispatch_app_action",
        AsyncMock(return_value=fake_result),
    ) as patched:
        result = await invoke_app_action_executor(params, context)

    assert result["success"] is True
    forwarded_run_id = patched.await_args.kwargs["run_id"]
    assert isinstance(forwarded_run_id, UUID)
    assert forwarded_run_id == run_id
    # Default empty input dict when omitted.
    assert patched.await_args.kwargs["input"] == {}


# ---------------------------------------------------------------------------
# Executor: failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_returns_structured_error_on_dispatch_error():
    """ActionDispatchError must NOT propagate — surface as ok=False."""
    from app.services.apps.action_dispatcher import ActionInputInvalid

    instance_id = uuid4()
    db = AsyncMock()
    context = {"db": db}
    params = {
        "app_instance_id": str(instance_id),
        "action_name": "summarize_pipeline",
        "input": {"wrong_key": 1},
    }

    boom = ActionInputInvalid("schema validation failed: 'pipeline_id' is required")

    with patch(
        "app.services.apps.action_dispatcher.dispatch_app_action",
        AsyncMock(side_effect=boom),
    ):
        # MUST NOT raise — agent has to receive a parseable result.
        result = await invoke_app_action_executor(params, context)

    assert result["success"] is False
    assert result["ok"] is False
    assert result["error"] == "ActionInputInvalid"
    assert "schema validation failed" in result["error_message"]
    # Should also include a human-readable suggestion to help the agent.
    assert "suggestion" in result


@pytest.mark.asyncio
async def test_executor_returns_structured_error_on_unexpected_exception():
    """Unexpected dispatcher bugs MUST also be wrapped, not propagated."""
    instance_id = uuid4()
    db = AsyncMock()
    context = {"db": db}
    params = {
        "app_instance_id": str(instance_id),
        "action_name": "broken",
    }

    with patch(
        "app.services.apps.action_dispatcher.dispatch_app_action",
        AsyncMock(side_effect=RuntimeError("kaboom")),
    ):
        result = await invoke_app_action_executor(params, context)

    assert result["success"] is False
    assert result["ok"] is False
    assert result["error"] == "RuntimeError"
    assert "kaboom" in result["error_message"]


@pytest.mark.asyncio
async def test_executor_rejects_missing_app_instance_id():
    db = AsyncMock()
    result = await invoke_app_action_executor(
        {"action_name": "noop"}, {"db": db}
    )
    assert result["success"] is False
    assert result["ok"] is False
    assert "app_instance_id" in result["message"]


@pytest.mark.asyncio
async def test_executor_rejects_missing_action_name():
    db = AsyncMock()
    result = await invoke_app_action_executor(
        {"app_instance_id": str(uuid4())}, {"db": db}
    )
    assert result["success"] is False
    assert result["ok"] is False
    assert "action_name" in result["message"]


@pytest.mark.asyncio
async def test_executor_rejects_non_uuid_app_instance_id():
    db = AsyncMock()
    result = await invoke_app_action_executor(
        {"app_instance_id": "not-a-uuid", "action_name": "noop"},
        {"db": db},
    )
    assert result["success"] is False
    assert result["ok"] is False
    assert "UUID" in result["message"]


@pytest.mark.asyncio
async def test_executor_rejects_non_dict_input():
    db = AsyncMock()
    result = await invoke_app_action_executor(
        {
            "app_instance_id": str(uuid4()),
            "action_name": "noop",
            "input": "not-a-dict",
        },
        {"db": db},
    )
    assert result["success"] is False
    assert result["ok"] is False
    assert "input must be a dict" in result["message"]


@pytest.mark.asyncio
async def test_executor_rejects_missing_db_session():
    result = await invoke_app_action_executor(
        {"app_instance_id": str(uuid4()), "action_name": "noop"},
        {},  # no db
    )
    assert result["success"] is False
    assert result["ok"] is False
    assert "Database session" in result["message"]
