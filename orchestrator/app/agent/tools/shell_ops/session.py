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
    from fastapi import HTTPException

    project_id = context["project_id"]
    command = params.get("command", "/bin/sh")  # Alpine-based containers use sh, not bash
    user_id = context["user_id"]
    db = context["db"]

    # Get container info for multi-container projects
    container_name = context.get("container_name")

    session_manager = get_shell_session_manager()

    try:
        session_info = await session_manager.create_session(
            user_id=user_id,
            project_id=project_id,
            db=db,
            command=command,
            container_name=container_name,
        )

        session_id = session_info["session_id"]

        return success_output(
            message=f"Opened shell session {session_id}",
            session_id=session_id,
            details={
                "command": command
            }
        )
    except HTTPException as e:
        if e.status_code == 429:  # Too many sessions
            # Get existing sessions to help the LLM
            existing_sessions = await session_manager.list_sessions(user_id, project_id, db)

            session_list = "\n".join([
                f"  - {s['session_id']} (created: {s['created_at']}, last active: {s['last_activity_at']})"
                for s in existing_sessions
            ])

            error_msg = (
                f"Session limit reached. {len(existing_sessions)} active session(s):\n{session_list}\n\n"
                f"Options: 1) Use existing session_id with shell_exec, or 2) Close old session with shell_close."
            )

            raise ValueError(error_msg)
        else:
            raise


async def shell_close_executor(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Close a shell session."""
    from ....services.shell_session_manager import get_shell_session_manager

    session_id = params["session_id"]
    db = context["db"]

    session_manager = get_shell_session_manager()
    await session_manager.close_session(session_id, db)

    return success_output(
        message=f"Closed shell session {session_id}",
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
            '{"tool_name": "shell_open", "parameters": {}}',
            '{"tool_name": "shell_open", "parameters": {"command": "/bin/sh"}}'
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
            '{"tool_name": "shell_close", "parameters": {"session_id": "abc123"}}'
        ]
    ))

    logger.info("Registered 2 shell session management tools")
