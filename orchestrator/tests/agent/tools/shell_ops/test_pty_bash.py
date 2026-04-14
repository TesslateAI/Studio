"""
Tests for the upgraded local-mode ``bash_exec`` tool.

Exercises:
- Simple command completion with stdout capture.
- Return-code propagation for failing commands.
- Hard timeout kill path.
- cat + heredoc input via the idle-timeout path (confirms PTY input).
- ANSI colour output is stripped before being returned.
- Output-token truncation for noisy commands.
- Background spawn returns immediately with a session id.
"""

from __future__ import annotations

import pytest

from app.agent.tools.shell_ops.bash import bash_exec_tool
from app.services.orchestration.local import PTY_SESSIONS

from .conftest import requires_pty

pytestmark = [requires_pty, pytest.mark.asyncio]


async def test_echo_foreground_exits_with_stdout():
    result = await bash_exec_tool(
        {"command": "echo hello-pty", "timeout": 10},
        {"run_id": "pty-echo"},
    )
    assert result["success"] is True
    details = result["details"]
    assert details["status"] == "exited"
    assert details["exit_code"] == 0
    assert "hello-pty" in details["output"]
    assert details["truncated"] is False


async def test_nonzero_exit_is_reported_as_error():
    result = await bash_exec_tool(
        {"command": "sh -c 'exit 7'", "timeout": 10},
        {"run_id": "pty-exit"},
    )
    assert result["success"] is False
    details = result["details"]
    assert details["exit_code"] == 7
    assert details["tier"] == "local"


async def test_sleep_is_killed_on_timeout():
    result = await bash_exec_tool(
        {"command": "sleep 30", "timeout": 1, "yield_time_ms": 0},
        {"run_id": "pty-timeout"},
    )
    assert result["success"] is False
    details = result["details"]
    assert details["exit_code"] == 124
    # The registry must be empty — the tool closes the session on timeout.
    assert not any(e["session_id"] == details.get("session_id") for e in PTY_SESSIONS.list())


async def test_cat_receives_heredoc_input_via_shell():
    # Use a here-doc piped into cat so we exercise PTY input redirection
    # without depending on interactive write_stdin semantics.
    cmd = "cat <<'EOF'\nline-one\nline-two\nEOF\n"
    result = await bash_exec_tool(
        {"command": cmd, "timeout": 10, "yield_time_ms": 0},
        {"run_id": "pty-cat"},
    )
    assert result["success"] is True, result
    output = result["details"]["output"]
    assert "line-one" in output
    assert "line-two" in output


async def test_ansi_codes_are_stripped():
    # printf emits raw escape codes; strip_ansi_codes should remove them.
    cmd = "printf '\\033[31mred-text\\033[0m\\n'"
    result = await bash_exec_tool(
        {"command": cmd, "timeout": 10},
        {"run_id": "pty-ansi"},
    )
    assert result["success"] is True
    output = result["details"]["output"]
    assert "red-text" in output
    assert "\x1b[" not in output


async def test_output_truncation_kicks_in_at_budget():
    # 2000 bytes of noise with a 100-token budget (~400 bytes).
    cmd = "yes hellohello | head -c 2000"
    result = await bash_exec_tool(
        {
            "command": cmd,
            "timeout": 10,
            "yield_time_ms": 0,
            "max_output_tokens": 100,
        },
        {"run_id": "pty-trunc"},
    )
    assert result["success"] is True
    details = result["details"]
    assert details["truncated"] is True
    assert len(details["output"].encode("utf-8")) <= 100 * 4 + len("\n[truncated]\n")


async def test_background_spawn_returns_immediately():
    result = await bash_exec_tool(
        {"command": "sleep 0.5", "is_background": True},
        {"run_id": "pty-bg"},
    )
    assert result["success"] is True
    session_id = result["session_id"]
    assert isinstance(session_id, str) and len(session_id) > 0
    assert result["details"]["is_background"] is True
    # Session is registered against the run_id we passed in.
    snapshots = PTY_SESSIONS.list_by_run("pty-bg")
    assert any(s["session_id"] == session_id for s in snapshots)
    # Clean up to avoid leaking into other tests.
    PTY_SESSIONS.close(session_id)
