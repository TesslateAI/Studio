"""
Background Process Tools

Two tools for inspecting background PTY sessions spawned via
``bash_exec`` with ``is_background=True`` (or long-running foreground
sessions that yielded with ``status=running``):

- ``list_background_processes``: enumerate the sessions scoped to the
  current invocation.
- ``read_background_output``: peek at the most recent N lines of a
  session's accumulated output.

Security: sessions are tagged with a ``run_id`` (derived from
``context["run_id"]`` / ``chat_id`` / ``task_id`` / ``message_id``) at
creation time, and these tools filter the registry by that ``run_id``.
When no invocation identifier can be resolved, the tools fall back to
the global registry view — this matches the local-mode expectation that
a single process is acting as a single user.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from ..output_formatter import error_output, strip_ansi_codes, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)

_BYTES_PER_TOKEN = 4
_DEFAULT_TAIL_LINES = 200
_MAX_HISTORY_BYTES = 64 * 1024


def _resolve_run_id(context: dict[str, Any]) -> str | None:
    for key in ("run_id", "chat_id", "task_id", "message_id"):
        value = context.get(key)
        if value:
            return str(value)
    return None


def _format_started_at(started_at: float) -> str:
    try:
        return datetime.fromtimestamp(started_at, tz=UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        return str(started_at)


async def list_background_processes_tool(
    params: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Return the list of background PTY sessions scoped to this invocation."""
    from ....services.orchestration.local import PTY_SESSIONS

    run_id = _resolve_run_id(context)
    snapshots = PTY_SESSIONS.list_by_run(run_id)

    sessions: list[dict[str, Any]] = []
    for entry in snapshots:
        sessions.append(
            {
                "session_id": entry["session_id"],
                "command": entry["command"],
                "pid": entry["pid"],
                "started_at": _format_started_at(entry["started_at"]),
                "status": entry["status"],
                "exit_code": entry.get("exit_code"),
            }
        )

    logger.info(
        "[LIST-BG] run_id=%s found %d sessions",
        run_id,
        len(sessions),
    )

    return success_output(
        message=(
            f"{len(sessions)} background session(s)" if sessions else "No background sessions"
        ),
        sessions=sessions,
        details={"count": len(sessions), "run_id": run_id, "tier": "local"},
    )


async def read_background_output_tool(
    params: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Return the tail of a background session's accumulated output."""
    session_id = params.get("session_id")
    if not session_id or not isinstance(session_id, str):
        raise ValueError("session_id parameter is required")

    lines = int(params.get("lines", _DEFAULT_TAIL_LINES))
    if lines <= 0:
        raise ValueError("lines must be a positive integer")

    delay_ms = int(params.get("delay_ms", 0))
    if delay_ms < 0:
        raise ValueError("delay_ms must be >= 0")

    from ....services.orchestration.local import PTY_SESSIONS

    if not PTY_SESSIONS.has(session_id):
        return error_output(
            message=f"Unknown background session: {session_id}",
            suggestion="Call list_background_processes to see valid session IDs",
            details={"session_id": session_id, "tier": "local"},
        )

    # Scope by run_id: only sessions created by this invocation (or any,
    # when no run_id can be resolved) are visible.
    caller_run_id = _resolve_run_id(context)
    session_run_id = PTY_SESSIONS.get_run_id(session_id)
    if caller_run_id is not None and session_run_id != caller_run_id:
        return error_output(
            message=f"Access denied: session {session_id} belongs to another invocation",
            suggestion="Use list_background_processes to see sessions owned by this invocation",
            details={"session_id": session_id, "tier": "local"},
        )

    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000.0)

    try:
        raw = PTY_SESSIONS.read_history(session_id, max_bytes=_MAX_HISTORY_BYTES)
    except KeyError:
        return error_output(
            message=f"Unknown background session: {session_id}",
            suggestion="Session was removed before the read completed",
            details={"session_id": session_id, "tier": "local"},
        )

    text = raw.decode("utf-8", errors="replace") if raw else ""
    clean = strip_ansi_codes(text)

    all_lines = clean.split("\n")
    # Trailing empty element from a final newline is cosmetic; drop it.
    if all_lines and all_lines[-1] == "":
        all_lines.pop()

    total_lines = len(all_lines)
    if total_lines > lines:
        tail_lines = all_lines[-lines:]
        truncated = True
    else:
        tail_lines = all_lines
        truncated = False

    output = "\n".join(tail_lines)

    status_snapshot = PTY_SESSIONS.status(session_id)

    logger.info(
        "[READ-BG] session=%s lines=%d/%d status=%s truncated=%s",
        session_id,
        len(tail_lines),
        total_lines,
        status_snapshot["status"],
        truncated,
    )

    return success_output(
        message=(
            f"Read {len(tail_lines)} line(s) from session {session_id}"
            if tail_lines
            else f"Session {session_id} has produced no output yet"
        ),
        session_id=session_id,
        output=output,
        status=status_snapshot["status"],
        truncated=truncated,
        details={
            "session_id": session_id,
            "status": status_snapshot["status"],
            "exit_code": status_snapshot.get("exit_code"),
            "total_lines": total_lines,
            "returned_lines": len(tail_lines),
            "truncated": truncated,
            "tier": "local",
        },
    )


def register_background_tools(registry) -> None:
    """Register the background-process inspection tools on ``registry``."""
    registry.register(
        Tool(
            name="list_background_processes",
            description=(
                "List background PTY sessions spawned by bash_exec in this "
                "invocation. Returns session_id, command, pid, started_at, "
                "status, and exit_code for each live or recently-exited session."
            ),
            category=ToolCategory.SHELL,
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            executor=list_background_processes_tool,
            # No params in, list of session metadata dicts out — JSON-clean.
            state_serializable=True,
            # Pure inspection over the background-session registry; the
            # processes themselves are external state but this tool only reads.
            holds_external_state=False,
            examples=[
                '{"tool_name": "list_background_processes", "parameters": {}}',
            ],
        )
    )

    registry.register(
        Tool(
            name="read_background_output",
            description=(
                "Read the tail of a background PTY session's accumulated output "
                "(up to the last `lines` lines). Use list_background_processes "
                "to discover valid session IDs. Non-destructive — multiple "
                "reads return the same tail."
            ),
            category=ToolCategory.SHELL,
            parameters={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Background PTY session ID.",
                    },
                    "lines": {
                        "type": "integer",
                        "description": f"Number of tail lines to return (default: {_DEFAULT_TAIL_LINES}).",
                        "default": _DEFAULT_TAIL_LINES,
                    },
                    "delay_ms": {
                        "type": "integer",
                        "description": "Optional wait in milliseconds before reading, to let the process make progress.",
                        "default": 0,
                    },
                },
                "required": ["session_id"],
            },
            executor=read_background_output_tool,
            # session_id + tail params in, output text dict out — JSON-clean.
            state_serializable=True,
            # Reads from the live PTY ringbuffer of an out-of-band background
            # process; the underlying handle is external state.
            holds_external_state=True,
            examples=[
                '{"tool_name": "read_background_output", "parameters": {"session_id": "abc123"}}',
                '{"tool_name": "read_background_output", "parameters": {"session_id": "abc123", "lines": 50, "delay_ms": 500}}',
            ],
        )
    )

    logger.info("Registered 2 background-process tools")
