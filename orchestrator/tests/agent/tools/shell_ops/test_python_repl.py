"""
Tests for the persistent Python REPL tool.
"""

from __future__ import annotations

import pytest

from app.agent.tools.shell_ops.python_repl import (
    PYTHON_REPL_SESSIONS,
    python_repl_tool,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _cleanup_repl_sessions():
    yield
    # Drop any sessions created during the test so they don't bleed.
    # Snapshot the keys first — _sessions is mutated during drop.
    for sid in list(PYTHON_REPL_SESSIONS._sessions.keys()):  # noqa: SLF001
        PYTHON_REPL_SESSIONS.drop(sid)


async def test_expression_returns_value():
    result = await python_repl_tool(
        {"code": "2 + 2"},
        {"run_id": "repl-expr"},
    )
    assert result["success"] is True
    assert result["value"] == "4"
    assert result["stdout"] == ""
    assert result["stderr"] == ""
    assert result["timed_out"] is False
    assert isinstance(result["session_id"], str)


async def test_statements_persist_across_calls():
    first = await python_repl_tool(
        {"code": "x = 5"},
        {"run_id": "repl-persist"},
    )
    session_id = first["session_id"]
    assert first["success"] is True
    assert first["value"] is None

    second = await python_repl_tool(
        {"code": "print(x)", "session_id": session_id},
        {"run_id": "repl-persist"},
    )
    assert second["success"] is True
    assert second["stdout"] == "5\n"
    assert second["value"] is None


async def test_reset_drops_state():
    first = await python_repl_tool(
        {"code": "x = 99"},
        {"run_id": "repl-reset"},
    )
    session_id = first["session_id"]

    # Reset the same session and try to use x — should raise NameError.
    second = await python_repl_tool(
        {"code": "print(x)", "session_id": session_id, "reset": True},
        {"run_id": "repl-reset"},
    )
    assert second["success"] is True
    assert "NameError" in second["stderr"]


async def test_exception_captured_into_stderr():
    result = await python_repl_tool(
        {"code": "raise ValueError('boom')"},
        {"run_id": "repl-exc"},
    )
    assert result["success"] is True
    assert "ValueError" in result["stderr"]
    assert "boom" in result["stderr"]


async def test_infinite_loop_times_out_and_marks_bad():
    result = await python_repl_tool(
        {"code": "while True: pass", "timeout_ms": 250},
        {"run_id": "repl-timeout"},
    )
    assert result["success"] is True
    assert result["timed_out"] is True
    session_id = result["session_id"]

    # Second call without reset must be rejected with a 'bad session' error.
    followup = await python_repl_tool(
        {"code": "1 + 1", "session_id": session_id},
        {"run_id": "repl-timeout"},
    )
    assert followup.get("success") is False
    assert "bad" in followup["message"].lower()

    # Reset recovers.
    recovered = await python_repl_tool(
        {"code": "1 + 1", "session_id": session_id, "reset": True},
        {"run_id": "repl-timeout"},
    )
    assert recovered["success"] is True
    assert recovered["value"] == "2"
