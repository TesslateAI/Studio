"""
Bash Convenience Tool

Simplified wrapper for one-off command execution.
Auto-manages shell session lifecycle.
"""

import logging
from typing import Dict, Any
from uuid import UUID

from ..registry import Tool, ToolCategory
from .session import shell_open_executor, shell_close_executor
from .execute import shell_exec_executor
from ..output_formatter import success_output, error_output

logger = logging.getLogger(__name__)


async def bash_exec_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a single command (convenience wrapper).

    Opens a shell session, executes the command, returns output, and closes the session.
    Use this for one-off commands. For multiple commands, use shell_open + shell_exec.

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

    session_id = None
    try:
        # 1. Open session
        session_result = await shell_open_executor({}, context)
        if not session_result.get("success"):
            return error_output(
                message="Failed to open shell session",
                suggestion="Check if the dev container is running",
                details={"error": str(session_result)}
            )

        session_id = session_result["session_id"]

        # 2. Execute command
        exec_result = await shell_exec_executor({
            "session_id": session_id,
            "command": command,
            "wait_seconds": wait_seconds
        }, context)

        # 3. Close session
        await shell_close_executor({"session_id": session_id}, context)

        # 4. Return execution result
        return success_output(
            message=f"Executed '{command}'",
            output=exec_result.get("output", ""),
            details={
                "command": command,
                "exit_code": 0  # We don't capture exit codes yet
            }
        )

    except Exception as e:
        # Cleanup: try to close session if it was opened
        if session_id:
            try:
                await shell_close_executor({"session_id": session_id}, context)
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
            '<tool_call><tool_name>bash_exec</tool_name><parameters>{"command": "npm install"}</parameters></tool_call>',
            '<tool_call><tool_name>bash_exec</tool_name><parameters>{"command": "ls -la", "wait_seconds": 1.0}</parameters></tool_call>'
        ]
    ))

    logger.info("Registered 1 bash convenience tool")
