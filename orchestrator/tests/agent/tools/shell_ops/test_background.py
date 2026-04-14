"""
Tests for the background-process inspection tools.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agent.tools.shell_ops.background import (
    list_background_processes_tool,
    read_background_output_tool,
)
from app.agent.tools.shell_ops.bash import bash_exec_tool
from app.services.orchestration.local import PTY_SESSIONS

from .conftest import requires_pty

pytestmark = [requires_pty, pytest.mark.asyncio]


async def test_list_then_read_background_output():
    # Spawn a small script that emits output then exits.
    cmd = "sh -c 'for i in 1 2 3; do echo line-$i; done; sleep 0.1'"
    bg = await bash_exec_tool(
        {"command": cmd, "is_background": True},
        {"run_id": "bg-list"},
    )
    session_id = bg["session_id"]

    # Listing should return exactly the session we just created.
    listing = await list_background_processes_tool({}, {"run_id": "bg-list"})
    assert listing["success"] is True
    entries = listing["sessions"]
    assert any(e["session_id"] == session_id for e in entries)

    # Read a partial view first — may or may not have all lines yet.
    first = await read_background_output_tool(
        {"session_id": session_id, "lines": 10, "delay_ms": 50},
        {"run_id": "bg-list"},
    )
    assert first["success"] is True

    # Give the command time to finish, then read again.
    await asyncio.sleep(0.5)
    final = await read_background_output_tool(
        {"session_id": session_id, "lines": 10},
        {"run_id": "bg-list"},
    )
    assert final["success"] is True
    output = final["output"]
    assert "line-1" in output
    assert "line-2" in output
    assert "line-3" in output
    assert final["status"] in ("exited", "running")

    # Clean up.
    PTY_SESSIONS.close(session_id)


async def test_read_background_output_rejects_unknown_session():
    result = await read_background_output_tool(
        {"session_id": "ghost-session"},
        {"run_id": "bg-err"},
    )
    assert result["success"] is False
    assert "ghost-session" in result["message"]


async def test_read_background_output_denies_cross_run_access():
    # Create a session under run_id A, then try to read it from run_id B.
    bg = await bash_exec_tool(
        {"command": "sleep 5", "is_background": True},
        {"run_id": "run-a"},
    )
    session_id = bg["session_id"]
    try:
        denied = await read_background_output_tool(
            {"session_id": session_id},
            {"run_id": "run-b"},
        )
        assert denied["success"] is False
        assert "another invocation" in denied["message"]
    finally:
        PTY_SESSIONS.close(session_id)


async def test_list_scopes_by_run_id():
    # Two separate runs should only see their own sessions.
    a = await bash_exec_tool(
        {"command": "sleep 5", "is_background": True},
        {"run_id": "scope-a"},
    )
    b = await bash_exec_tool(
        {"command": "sleep 5", "is_background": True},
        {"run_id": "scope-b"},
    )
    sid_a = a["session_id"]
    sid_b = b["session_id"]

    try:
        listing_a = await list_background_processes_tool({}, {"run_id": "scope-a"})
        listing_b = await list_background_processes_tool({}, {"run_id": "scope-b"})
        ids_a = {e["session_id"] for e in listing_a["sessions"]}
        ids_b = {e["session_id"] for e in listing_b["sessions"]}
        assert sid_a in ids_a
        assert sid_a not in ids_b
        assert sid_b in ids_b
        assert sid_b not in ids_a
    finally:
        PTY_SESSIONS.close(sid_a)
        PTY_SESSIONS.close(sid_b)
