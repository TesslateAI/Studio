"""
Shell Execution Tools

Tools for executing commands in shell sessions.

Retry Strategy:
- Automatically retries on transient failures (ConnectionError, TimeoutError, IOError)
- Exponential backoff: 1s → 2s → 4s (up to 3 attempts)
"""

import asyncio
import base64
import logging
from typing import Any

from ..output_formatter import error_output, strip_ansi_codes, success_output
from ..registry import Tool, ToolCategory
from ..retry_config import tool_retry

logger = logging.getLogger(__name__)

_BYTES_PER_TOKEN = 4
_TRUNCATION_MARKER = "\n[truncated]\n"


def _truncate_output(text: str, max_output_tokens: int) -> tuple[str, bool]:
    """Truncate ``text`` to at most ``max_output_tokens * 4`` bytes.

    Keeps the tail of the output — shell tools typically emit the
    interesting bit last.
    """
    if max_output_tokens <= 0:
        return text, False
    budget = max_output_tokens * _BYTES_PER_TOKEN
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= budget:
        return text, False
    tail = encoded[-budget:]
    try:
        decoded = tail.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        decoded = tail.decode("latin-1", errors="replace")
    return _TRUNCATION_MARKER + decoded, True


@tool_retry
async def shell_exec_executor(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Execute command and return output.

    Retry behavior:
    - Automatically retries on ConnectionError, TimeoutError, IOError
    - Up to 3 attempts with exponential backoff (1s, 2s, 4s)
    """
    from ....services.shell_session_manager import get_shell_session_manager

    session_id = params["session_id"]
    command = params["command"]
    wait_seconds = params.get("wait_seconds", 2.0)
    max_output_tokens_raw = params.get("max_output_tokens")
    max_output_tokens = int(max_output_tokens_raw) if max_output_tokens_raw is not None else None
    db = context["db"]
    user_id = context["user_id"]

    # Add newline if not present
    if not command.endswith("\n"):
        command += "\n"

    session_manager = get_shell_session_manager()

    # Write command (with authorization check)
    data_bytes = command.encode("utf-8")
    try:
        await session_manager.write_to_session(session_id, data_bytes, db, user_id=user_id)
    except KeyError:
        return error_output(
            message=f"Unknown shell session: {session_id}",
            suggestion=(
                "Call shell_open first to obtain a session_id, or the session may have exited."
            ),
            details={
                "session_id": session_id,
                "status": "unknown",
                "tier": "orchestrator",
            },
        )
    except BrokenPipeError as exc:
        return error_output(
            message=f"Shell session {session_id} pipe is broken: {exc}",
            suggestion="The session may have exited — open a new session with shell_open",
            details={
                "session_id": session_id,
                "error": str(exc),
                "status": "exited",
                "tier": "orchestrator",
            },
        )

    # Wait for execution
    await asyncio.sleep(wait_seconds)

    # Read output (with authorization check)
    try:
        output_data = await session_manager.read_output(session_id, db, user_id=user_id)
    except KeyError:
        return error_output(
            message=f"Unknown shell session: {session_id}",
            suggestion="Session was removed between write and read",
            details={
                "session_id": session_id,
                "status": "unknown",
                "tier": "orchestrator",
            },
        )
    except BrokenPipeError as exc:
        return error_output(
            message=f"Shell session {session_id} pipe is broken: {exc}",
            suggestion="The session may have exited — open a new session with shell_open",
            details={
                "session_id": session_id,
                "error": str(exc),
                "status": "exited",
                "tier": "orchestrator",
            },
        )

    # Decode base64 output and strip control characters
    output_text = base64.b64decode(output_data["output"]).decode("utf-8", errors="replace")
    output_text = strip_ansi_codes(output_text)

    truncated = False
    if max_output_tokens is not None and max_output_tokens > 0:
        output_text, truncated = _truncate_output(output_text, max_output_tokens)

    # Determine session status / exit_code from what the manager exposes
    # (is_eof → exited; otherwise → running). The manager does not surface a
    # process exit_code directly, so we attach it only when we can infer it.
    is_eof = bool(output_data.get("is_eof"))
    status = "exited" if is_eof else "running"
    exit_code: int | None = None
    session = session_manager.active_sessions.get(session_id)
    if session is not None:
        # Best-effort: some PTY session implementations expose ``exit_code``
        # once the underlying process has terminated. Read it defensively.
        candidate = getattr(session, "exit_code", None)
        if candidate is not None:
            try:
                exit_code = int(candidate)
            except (TypeError, ValueError):
                exit_code = None

    details: dict[str, Any] = {
        "bytes": output_data["bytes"],
        "is_eof": is_eof,
        "status": status,
        "tier": "orchestrator",
    }
    if exit_code is not None:
        details["exit_code"] = exit_code
    if truncated:
        details["truncated"] = True

    return success_output(
        message=f"Executed '{command.strip()}' in session {session_id}",
        output=output_text,
        session_id=session_id,
        details=details,
    )


def register_execute_tools(registry):
    """Register shell execution tool."""

    registry.register(
        Tool(
            name="shell_exec",
            description="Execute a command in an open shell session and wait for output. REQUIRES session_id from shell_open first. DO NOT use 'exit' or close the shell - it stays open for multiple commands.",
            category=ToolCategory.SHELL,
            parameters={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Shell session ID obtained from shell_open",
                    },
                    "command": {
                        "type": "string",
                        "description": "Command to execute (automatically adds \\n). DO NOT include 'exit' - the shell stays open.",
                    },
                    "wait_seconds": {
                        "type": "number",
                        "description": "Seconds to wait before reading output (default: 2)",
                    },
                    "max_output_tokens": {
                        "type": "integer",
                        "description": (
                            "Approximate output budget in model tokens (4 bytes/token). "
                            "When provided, output beyond this is truncated with a "
                            "[truncated] marker. Default: unbounded."
                        ),
                    },
                },
                "required": ["session_id", "command"],
            },
            executor=shell_exec_executor,
            # session_id + command in, captured output dict out — JSON-serializable.
            state_serializable=True,
            # Operates on a persistent PTY/shell session opened by shell_open;
            # the underlying file descriptor + PTY state lives outside the run
            # and cannot be checkpointed.
            holds_external_state=True,
            examples=[
                '{"tool_name": "shell_exec", "parameters": {"session_id": "abc123", "command": "npm install"}}',
                '{"tool_name": "shell_exec", "parameters": {"session_id": "abc123", "command": "echo \'Hello\'"}}',
            ],
        )
    )

    logger.info("Registered 1 shell execution tool")
