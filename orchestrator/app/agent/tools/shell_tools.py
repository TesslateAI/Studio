"""
Shell Tools for Universal Agent

Provides interactive shell session capabilities to AI agents.
"""

import asyncio
import base64
import logging
from typing import Dict, Any

from .registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


async def shell_open_executor(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Open a new shell session."""
    from ...services.shell_session_manager import get_shell_session_manager

    project_id = params["project_id"]
    command = params.get("command", "/bin/bash")
    cwd = params.get("cwd", "/app/project")
    user_id = context["user_id"]
    db = context["db"]

    session_manager = get_shell_session_manager()

    session_info = await session_manager.create_session(
        user_id=user_id,
        project_id=project_id,
        db=db,
        command=command,
        cwd=cwd,
    )

    return {
        "success": True,
        "session_id": session_info["session_id"],
        "message": f"Shell session opened: {session_info['session_id'][:8]}",
    }


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

    # Decode base64 output
    output_text = base64.b64decode(output_data["output"]).decode('utf-8', errors='replace')

    return {
        "success": True,
        "output": output_text,
        "bytes": output_data["bytes"],
        "is_eof": output_data["is_eof"],
    }


async def shell_write_executor(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Write data to shell session."""
    from ...services.shell_session_manager import get_shell_session_manager

    session_id = params["session_id"]
    data = params["data"]
    db = context["db"]

    session_manager = get_shell_session_manager()

    data_bytes = data.encode('utf-8')
    await session_manager.write_to_session(session_id, data_bytes, db)

    return {
        "success": True,
        "bytes_written": len(data_bytes),
    }


async def shell_read_executor(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Read new output from shell session."""
    from ...services.shell_session_manager import get_shell_session_manager

    session_id = params["session_id"]
    db = context["db"]

    session_manager = get_shell_session_manager()
    output_data = await session_manager.read_output(session_id, db)

    # Decode base64 output
    output_text = base64.b64decode(output_data["output"]).decode('utf-8', errors='replace')

    return {
        "success": True,
        "output": output_text,
        "bytes": output_data["bytes"],
        "is_eof": output_data["is_eof"],
    }


async def shell_list_executor(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """List active shell sessions."""
    from ...services.shell_session_manager import get_shell_session_manager

    user_id = context["user_id"]
    project_id = params.get("project_id")
    db = context["db"]

    session_manager = get_shell_session_manager()

    sessions = await session_manager.list_sessions(
        user_id=user_id,
        project_id=project_id,
        db=db,
    )

    return {
        "success": True,
        "sessions": sessions,
        "count": len(sessions),
    }


async def shell_close_executor(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Close a shell session."""
    from ...services.shell_session_manager import get_shell_session_manager

    session_id = params["session_id"]
    db = context["db"]

    session_manager = get_shell_session_manager()
    await session_manager.close_session(session_id, db)

    return {
        "success": True,
        "message": f"Closed session {session_id[:8]}",
    }


def register_tools(registry):
    """Register all shell tools."""

    registry.register(Tool(
        name="shell_open",
        description="Open an interactive shell session in a development environment. Returns session_id for subsequent operations.",
        category=ToolCategory.SHELL,
        parameters={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "integer",
                    "description": "Project ID to open shell in",
                },
                "command": {
                    "type": "string",
                    "description": "Shell command to run (default: /bin/bash)",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory (default: /app/project)",
                },
            },
            "required": ["project_id"],
        },
        executor=shell_open_executor,
        examples=[
            'shell_open({"project_id": 123})',
            'shell_open({"project_id": 123, "command": "/bin/bash", "cwd": "/app/project"})'
        ]
    ))

    registry.register(Tool(
        name="shell_exec",
        description="Execute a command in an open shell session and wait for output. Convenience wrapper around shell_write + shell_read.",
        category=ToolCategory.SHELL,
        parameters={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Shell session ID from shell_open",
                },
                "command": {
                    "type": "string",
                    "description": "Command to execute (automatically adds \\n)",
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
            'shell_exec({"session_id": "abc123", "command": "npm test", "wait_seconds": 5})'
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
        description="List all active shell sessions for the current user",
        category=ToolCategory.SHELL,
        parameters={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "integer",
                    "description": "Filter by project ID (optional)",
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
