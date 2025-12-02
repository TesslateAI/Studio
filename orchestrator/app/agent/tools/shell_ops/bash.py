"""
Bash Convenience Tool

Simplified wrapper for one-off command execution.
Auto-manages shell session lifecycle.

Retry Strategy:
- Automatically retries on transient failures (ConnectionError, TimeoutError, IOError)
- Exponential backoff: 1s → 2s → 4s (up to 3 attempts)
"""

import logging
from typing import Dict, Any
from uuid import UUID

from ..registry import Tool, ToolCategory
from .session import shell_open_executor, shell_close_executor
from .execute import shell_exec_executor
from ..output_formatter import success_output, error_output
from ..retry_config import tool_retry

logger = logging.getLogger(__name__)


@tool_retry
async def bash_exec_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a single command (convenience wrapper).

    Reuses shell session within the same agent run for efficiency.
    Session is stored in context['_bash_session_id'] and reused across calls.

    Retry behavior:
    - Automatically retries on ConnectionError, TimeoutError, IOError
    - Up to 3 attempts with exponential backoff (1s, 2s, 4s)

    Args:
        params: {
            command: str,  # Command to execute
            wait_seconds: float  # Optional wait time (default: 2.0)
        }
        context: {user_id: UUID, project_id: str, db: AsyncSession}

    Returns:
        Dict with command output
    """
    command = params.get("command")
    wait_seconds = params.get("wait_seconds", 2.0)

    if not command:
        raise ValueError("command parameter is required")

    # Check if we have a reusable session from a previous bash_exec call
    session_id = context.get("_bash_session_id")
    session_created = False

    try:
        # 1. Open session only if we don't have one
        if not session_id:
            session_result = await shell_open_executor({}, context)
            if not session_result.get("success"):
                return error_output(
                    message="Failed to open shell session",
                    suggestion="Check if the dev container is running",
                    details={"error": str(session_result)}
                )

            session_id = session_result["session_id"]
            session_created = True
            # Store in context for reuse within this agent run
            context["_bash_session_id"] = session_id
            logger.info(f"[BASH] Created new session {session_id} for agent run")
        else:
            logger.debug(f"[BASH] Reusing existing session {session_id}")

        # 2. Execute command
        exec_result = await shell_exec_executor({
            "session_id": session_id,
            "command": command,
            "wait_seconds": wait_seconds
        }, context)

        # 3. Return execution result (session stays open for reuse)
        return success_output(
            message=f"Executed '{command}'",
            output=exec_result.get("output", ""),
            details={
                "command": command,
                "exit_code": 0,  # We don't capture exit codes yet
                "session_reused": not session_created
            }
        )

    except Exception as e:
        # On error, close and clear the session so next call creates a fresh one
        if session_id:
            try:
                await shell_close_executor({"session_id": session_id}, context)
                context.pop("_bash_session_id", None)
                logger.info(f"[BASH] Closed session {session_id} due to error")
            except Exception:
                pass  # Ignore cleanup errors

        return error_output(
            message=f"Command execution failed: {str(e)}",
            suggestion="Check your command syntax and try again",
            details={
                "command": command,
                "error": str(e)
            }
        )


def register_bash_tools(registry):
    """Register bash convenience tools."""

    registry.register(Tool(
        name="bash_exec",
        description="Execute a single bash/sh command (convenience wrapper). Auto-opens shell session, runs command, returns output, and closes session. For multiple commands, use shell_open + shell_exec for better performance.",
        category=ToolCategory.SHELL,
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Command to execute (e.g., 'npm install', 'ls -la')",
                },
                "wait_seconds": {
                    "type": "number",
                    "description": "Seconds to wait before reading output (default: 2.0)",
                    "default": 2.0
                },
            },
            "required": ["command"],
        },
        executor=bash_exec_tool,
        examples=[
            '{"tool_name": "bash_exec", "parameters": {"command": "npm install"}}',
            '{"tool_name": "bash_exec", "parameters": {"command": "ls -la", "wait_seconds": 1.0}}'
        ]
    ))

    logger.info("Registered 1 bash convenience tool")
