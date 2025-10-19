"""
Shell Tools for Universal Agent

Provides interactive shell session capabilities to AI agents.
"""

import asyncio
import base64
import logging
from typing import Dict, Any

from .registry import Tool, ToolCategory
from .output_formatter import success_output, error_output, truncate_session_id, pluralize, strip_ansi_codes

logger = logging.getLogger(__name__)


async def shell_open_executor(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Open a new shell session."""
    from ...services.shell_session_manager import get_shell_session_manager

    project_id = context["project_id"]  # Get from context, not params
    command = params.get("command", "/bin/sh")  # Alpine-based containers use sh, not bash
    user_id = context["user_id"]
    db = context["db"]

    session_manager = get_shell_session_manager()

    session_info = await session_manager.create_session(
        user_id=user_id,
        project_id=project_id,
        db=db,
        command=command,
    )

    session_id = session_info["session_id"]

    return success_output(
        message=f"Opened shell session {truncate_session_id(session_id)}",
        session_id=session_id,
        details={
            "command": command
        }
    )


async def shell_exec_executor(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Execute command and return output."""
    from ...services.shell_session_manager import get_shell_session_manager

    session_id = params["session_id"]
    command = params["command"]
    wait_seconds = params.get("wait_seconds", 2.0)
    db = context["db"]

    # Add newline if not present
    if not command.endswith("\n"):
        command += "\n"

    session_manager = get_shell_session_manager()

    # Write command
    data_bytes = command.encode('utf-8')
    await session_manager.write_to_session(session_id, data_bytes, db)

    # Wait for execution
    await asyncio.sleep(wait_seconds)

    # Read output
    output_data = await session_manager.read_output(session_id, db)

    # Decode base64 output and strip control characters
    output_text = base64.b64decode(output_data["output"]).decode('utf-8', errors='replace')
    output_text = strip_ansi_codes(output_text)

    return success_output(
        message=f"Executed '{command.strip()}' in session {truncate_session_id(session_id)}",
        output=output_text,
        session_id=session_id,
        details={
            "bytes": output_data["bytes"],
            "is_eof": output_data["is_eof"]
        }
    )


async def shell_write_executor(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Write data to shell session."""
    from ...services.shell_session_manager import get_shell_session_manager

    session_id = params["session_id"]
    data = params["data"]
    db = context["db"]

    session_manager = get_shell_session_manager()

    data_bytes = data.encode('utf-8')
    await session_manager.write_to_session(session_id, data_bytes, db)

    return success_output(
        message=f"Wrote data to session {truncate_session_id(session_id)}",
        session_id=session_id,
        details={"bytes_written": len(data_bytes)}
    )


async def shell_read_executor(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Read new output from shell session."""
    from ...services.shell_session_manager import get_shell_session_manager

    session_id = params["session_id"]
    db = context["db"]

    session_manager = get_shell_session_manager()
    output_data = await session_manager.read_output(session_id, db)

    # Decode base64 output and strip control characters
    output_text = base64.b64decode(output_data["output"]).decode('utf-8', errors='replace')
    output_text = strip_ansi_codes(output_text)

    return success_output(
        message=f"Read output from session {truncate_session_id(session_id)}",
        output=output_text,
        session_id=session_id,
        details={
            "bytes": output_data["bytes"],
            "is_eof": output_data["is_eof"]
        }
    )


async def shell_list_executor(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """List active shell sessions."""
    from ...services.shell_session_manager import get_shell_session_manager

    user_id = context["user_id"]
    project_id = params.get("project_id", context.get("project_id"))  # Default to current project
    db = context["db"]

    session_manager = get_shell_session_manager()

    sessions = await session_manager.list_sessions(
        user_id=user_id,
        project_id=project_id,
        db=db,
    )

    if len(sessions) == 0:
        message = "No active shell sessions"
    else:
        message = f"Found {pluralize(len(sessions), 'active shell session')}"

    return success_output(
        message=message,
        sessions=sessions,
        details={"count": len(sessions)}
    )


async def shell_close_executor(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Close a shell session."""
    from ...services.shell_session_manager import get_shell_session_manager

    session_id = params["session_id"]
    db = context["db"]

    session_manager = get_shell_session_manager()
    await session_manager.close_session(session_id, db)

    return success_output(
        message=f"Closed shell session {truncate_session_id(session_id)}",
        session_id=session_id
    )


def register_tools(registry):
    """Register all shell tools."""

    registry.register(Tool(
        name="shell_open",
        description="Open an interactive shell session in the current project directory. Returns session_id for subsequent operations. MUST be called before shell_exec, shell_write, or shell_read. The shell remains open until explicitly closed with shell_close.",
        category=ToolCategory.SHELL,
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to run (default: /bin/sh). The shell starts in the project directory with all your source files.",
                },
            },
            "required": [],
        },
        executor=shell_open_executor,
        examples=[
            'shell_open({})',
            'shell_open({"command": "/bin/sh"})'
        ]
    ))

    registry.register(Tool(
        name="shell_exec",
        description="Execute a command in an open shell session and wait for output. REQUIRES session_id from shell_open first. DO NOT use 'exit' or close the shell - it stays open for multiple commands. Convenience wrapper around shell_write + shell_read.",
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
            'shell_exec({"session_id": "abc123", "command": "npm install"})',
            'shell_exec({"session_id": "abc123", "command": "echo \'Hello\'"})'
        ]
    ))

    registry.register(Tool(
        name="shell_write",
        description="Write data to an open shell session stdin (low-level). Use shell_exec for convenience.",
        category=ToolCategory.SHELL,
        parameters={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Shell session ID",
                },
                "data": {
                    "type": "string",
                    "description": "Data to write to shell stdin (include \\n for commands)",
                },
            },
            "required": ["session_id", "data"],
        },
        executor=shell_write_executor,
        examples=[
            'shell_write({"session_id": "abc123", "data": "ls -la\\n"})'
        ]
    ))

    registry.register(Tool(
        name="shell_read",
        description="Read new output from shell session since last read. Returns base64-encoded output.",
        category=ToolCategory.SHELL,
        parameters={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Shell session ID",
                },
            },
            "required": ["session_id"],
        },
        executor=shell_read_executor,
        examples=[
            'shell_read({"session_id": "abc123"})'
        ]
    ))

    registry.register(Tool(
        name="shell_list",
        description="List all active shell sessions for the current user. Defaults to current project sessions.",
        category=ToolCategory.SHELL,
        parameters={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "integer",
                    "description": "Filter by project ID (optional, defaults to current project)",
                },
            },
            "required": [],
        },
        executor=shell_list_executor,
        examples=[
            'shell_list({})',
            'shell_list({"project_id": 123})'
        ]
    ))

    registry.register(Tool(
        name="shell_close",
        description="Close an active shell session. Always close sessions when done to free resources.",
        category=ToolCategory.SHELL,
        parameters={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Shell session ID to close",
                },
            },
            "required": ["session_id"],
        },
        executor=shell_close_executor,
        examples=[
            'shell_close({"session_id": "abc123"})'
        ]
    ))

    logger.info("Registered 6 shell tools")
