"""
write_stdin Tool

Writes characters into a running PTY-backed session spawned by ``bash_exec``
(either as a background process or as a yielded long-running command) and
drains whatever output arrives within a short window.

Semantics:
- ``session_id`` must identify a live session in :data:`PTY_SESSIONS`.
- ``chars`` is written verbatim — callers are responsible for including a
  trailing newline when simulating a pressed Enter key.
- ``yield_time_ms`` is the short drain window after the write (default 250
  ms) — the tool returns whatever output arrives in that window.
- ``max_output_tokens`` bounds the returned payload (4 bytes/token).

Local deployment mode only.
"""

from __future__ import annotations

import logging
from typing import Any

from ..output_formatter import error_output, strip_ansi_codes, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)

_BYTES_PER_TOKEN = 4
_TRUNCATION_MARKER = "\n[truncated]\n"


def _truncate_output(text: str, max_output_tokens: int) -> tuple[str, bool]:
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


async def write_stdin_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Write characters into a running PTY session and drain the response.

    Args:
        params: {
            session_id: str,
            chars: str,
            yield_time_ms: int = 250,
            max_output_tokens: int = 4096,
        }

    Returns:
        Dict with ``session_id``, ``new_output``, ``status``, optional
        ``return_code``, and ``truncated`` flag.
    """
    session_id = params.get("session_id")
    if not session_id or not isinstance(session_id, str):
        raise ValueError("session_id parameter is required")

    chars = params.get("chars")
    if chars is None:
        raise ValueError("chars parameter is required")
    if not isinstance(chars, str):
        raise ValueError("chars must be a string")

    yield_time_ms = int(params.get("yield_time_ms", 250))
    max_output_tokens = int(params.get("max_output_tokens", 4096))

    from ....services.orchestration.local import PTY_SESSIONS

    if not PTY_SESSIONS.has(session_id):
        return error_output(
            message=f"Unknown PTY session: {session_id}",
            suggestion=(
                "Use list_background_processes to see active sessions, or spawn a new "
                "one with bash_exec (is_background=True or a long-running foreground command)"
            ),
            details={"session_id": session_id, "tier": "local"},
        )

    try:
        PTY_SESSIONS.write(session_id, chars)
    except KeyError:
        return error_output(
            message=f"Unknown PTY session: {session_id}",
            suggestion="Session may have exited between status check and write",
            details={"session_id": session_id, "tier": "local"},
        )
    except (OSError, BrokenPipeError) as exc:
        return error_output(
            message=f"Failed to write to PTY session {session_id}: {exc}",
            suggestion="The session may have exited — check its status",
            details={"session_id": session_id, "error": str(exc), "tier": "local"},
        )

    max_bytes_budget = max_output_tokens * _BYTES_PER_TOKEN if max_output_tokens > 0 else None

    try:
        chunk = await PTY_SESSIONS.drain(
            session_id=session_id,
            max_duration_ms=max(0, yield_time_ms),
            idle_timeout_ms=0,
            max_bytes=max_bytes_budget,
            wait_for_exit=True,
        )
    except KeyError:
        return error_output(
            message=f"Unknown PTY session: {session_id}",
            suggestion="Session was removed during drain",
            details={"session_id": session_id, "tier": "local"},
        )

    text = chunk.decode("utf-8", errors="replace") if chunk else ""
    clean = strip_ansi_codes(text)
    clean, truncated = _truncate_output(clean, max_output_tokens)

    status_snapshot = PTY_SESSIONS.status(session_id)
    current_status = status_snapshot["status"]
    return_code = status_snapshot.get("exit_code")

    result_details: dict[str, Any] = {
        "session_id": session_id,
        "new_output": clean,
        "status": current_status,
        "truncated": truncated,
        "tier": "local",
    }
    if return_code is not None:
        result_details["return_code"] = return_code

    logger.info(
        "[WRITE-STDIN] session=%s status=%s bytes=%d truncated=%s",
        session_id,
        current_status,
        len(clean),
        truncated,
    )

    return success_output(
        message=f"Wrote {len(chars)} chars to session {session_id}",
        session_id=session_id,
        new_output=clean,
        status=current_status,
        truncated=truncated,
        details=result_details,
    )


def register_write_stdin_tool(registry) -> None:
    """Register the ``write_stdin`` tool on ``registry``."""
    registry.register(
        Tool(
            name="write_stdin",
            description=(
                "Write characters into a running PTY session previously created by "
                "bash_exec (either is_background=True or a yielded long-running "
                "command). Include a trailing newline to simulate pressing Enter. "
                "Returns whatever output arrives within yield_time_ms. Local mode only."
            ),
            category=ToolCategory.SHELL,
            parameters={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Identifier returned by bash_exec for the running PTY session.",
                    },
                    "chars": {
                        "type": "string",
                        "description": (
                            "Characters to send to the session's stdin. Include a "
                            "trailing '\\n' to simulate pressing Enter."
                        ),
                    },
                    "yield_time_ms": {
                        "type": "integer",
                        "description": "Drain window in milliseconds after the write (default: 250).",
                        "default": 250,
                    },
                    "max_output_tokens": {
                        "type": "integer",
                        "description": "Approximate token budget for the drained output (default: 4096).",
                        "default": 4096,
                    },
                },
                "required": ["session_id", "chars"],
            },
            executor=write_stdin_tool,
            # session_id + chars in, drained-output dict out — JSON-clean.
            state_serializable=True,
            # Writes into a live PTY whose file descriptor + child process
            # state lives outside the agent run.
            holds_external_state=True,
            examples=[
                '{"tool_name": "write_stdin", "parameters": {"session_id": "abc123", "chars": "hello\\n"}}',
                '{"tool_name": "write_stdin", "parameters": {"session_id": "abc123", "chars": "y\\n", "yield_time_ms": 500}}',
            ],
        )
    )

    logger.info("Registered write_stdin tool")
