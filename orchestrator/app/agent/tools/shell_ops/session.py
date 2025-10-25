"""
Shell Session Management Tools

Tools for managing persistent shell sessions in dev containers.
"""

import logging
from typing import Dict, Any

from ..registry import Tool, ToolCategory
from ..output_formatter import success_output, truncate_session_id, pluralize

logger = logging.getLogger(__name__)


async def shell_open_executor(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Open a new shell session in the dev container."""
    from ....services.shell_session_manager import get_shell_session_manager

    project_id = context["project_id"]
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


async def shell_close_executor(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Close a shell session."""
    from ....services.shell_session_manager import get_shell_session_manager

    session_id = params["session_id"]
    db = context["db"]

    session_manager = get_shell_session_manager()
    await session_manager.close_session(session_id, db)

    return success_output(
        message=f"Closed shell session {truncate_session_id(session_id)}",
        session_id=session_id
    )


def register_session_tools(registry):
    """Register shell session management tools."""

    registry.register(Tool(
        name="shell_open",
        description="Open an interactive shell session in the current project's dev container. Returns session_id for subsequent operations. MUST be called before shell_exec. The shell remains open until explicitly closed with shell_close.",
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

    logger.info("Registered 2 shell session management tools")
