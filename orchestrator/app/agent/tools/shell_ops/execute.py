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
from typing import Dict, Any

from ..registry import Tool, ToolCategory
from ..output_formatter import success_output, truncate_session_id, strip_ansi_codes
from ..retry_config import tool_retry

logger = logging.getLogger(__name__)


@tool_retry
async def shell_exec_executor(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
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
    db = context["db"]
    user_id = context["user_id"]

    # Add newline if not present
    if not command.endswith("\n"):
        command += "\n"

    session_manager = get_shell_session_manager()

    # Write command (with authorization check)
    data_bytes = command.encode('utf-8')
    await session_manager.write_to_session(session_id, data_bytes, db, user_id=user_id)

    # Wait for execution
    await asyncio.sleep(wait_seconds)

    # Read output (with authorization check)
    output_data = await session_manager.read_output(session_id, db, user_id=user_id)

    # Decode base64 output and strip control characters
    output_text = base64.b64decode(output_data["output"]).decode('utf-8', errors='replace')
    output_text = strip_ansi_codes(output_text)

    return success_output(
        message=f"Executed '{command.strip()}' in session {session_id}",
        output=output_text,
        session_id=session_id,
        details={
            "bytes": output_data["bytes"],
            "is_eof": output_data["is_eof"]
        }
    )


def register_execute_tools(registry):
    """Register shell execution tool."""

    registry.register(Tool(
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
            },
            "required": ["session_id", "command"],
        },
        executor=shell_exec_executor,
        examples=[
            '{"tool_name": "shell_exec", "parameters": {"session_id": "abc123", "command": "npm install"}}',
            '{"tool_name": "shell_exec", "parameters": {"session_id": "abc123", "command": "echo \'Hello\'"}}'
        ]
    ))

    logger.info("Registered 1 shell execution tool")
