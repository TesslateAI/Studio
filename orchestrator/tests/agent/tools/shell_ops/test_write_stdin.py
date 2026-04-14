"""
Tests for the ``write_stdin`` tool.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agent.tools.shell_ops.bash import bash_exec_tool
from app.agent.tools.shell_ops.write_stdin import write_stdin_tool
from app.services.orchestration.local import PTY_SESSIONS

from .conftest import requires_pty

pytestmark = [requires_pty, pytest.mark.asyncio]


async def test_write_stdin_round_trips_through_cat():
    # Spawn `cat` as a background session so we can write to its stdin.
    bg = await bash_exec_tool(
        {"command": "cat", "is_background": True},
        {"run_id": "stdin-cat"},
    )
    assert bg["success"] is True
    session_id = bg["session_id"]

    try:
        result = await write_stdin_tool(
            {"session_id": session_id, "chars": "hello-stdin\n", "yield_time_ms": 500},
            {"run_id": "stdin-cat"},
        )
        assert result["success"] is True
        # cat echoes back whatever we wrote on the PTY.
        assert "hello-stdin" in result["new_output"]
        # Process is still running after the echo.
        assert result["status"] == "running"
    finally:
        PTY_SESSIONS.close(session_id)

    # After close the session is gone.
    assert not PTY_SESSIONS.has(session_id)


async def test_write_stdin_unknown_session_id():
    result = await write_stdin_tool(
        {"session_id": "not-a-real-session", "chars": "oops\n"},
        {"run_id": "stdin-err"},
    )
    assert result.get("success") is False
    assert "not-a-real-session" in result["message"]


async def test_write_stdin_requires_chars():
    # Missing 'chars' must raise ValueError (caught by the tool registry).
    with pytest.raises(ValueError):
        await write_stdin_tool(
            {"session_id": "anything"},
            {"run_id": "stdin-err2"},
        )
    # Let the event loop settle.
    await asyncio.sleep(0)
