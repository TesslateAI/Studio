"""
Shell tools for graph view.

These tools allow the agent to connect to shells and execute commands
in specific containers when viewing the architecture graph.
"""

import logging
from typing import Dict, Any, List
from uuid import UUID

from ..registry import Tool, ToolCategory
from ..output_formatter import success_output, error_output

logger = logging.getLogger(__name__)


async def graph_shell_open_executor(
    params: Dict[str, Any],
    context: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Open a shell session in a specific container.

    Args:
        params: {
            "container_id": "uuid",
            "command": "/bin/sh" (optional)
        }
        context: Execution context

    Returns:
        Success/error output with session_id
    """
    container_id = params.get("container_id")
    if not container_id:
        return error_output(
            message="container_id is required",
            suggestion="Provide the UUID of the container to connect to"
        )

    db = context.get("db")
    user_id = context.get("user_id")
    project_id = context.get("project_id")

    if not db or not user_id or not project_id:
        return error_output(
            message="Missing required context",
            suggestion="Ensure db, user_id, and project_id are in context"
        )

    try:
        from sqlalchemy import select
        from ....models import Container
        from ....services.shell_session_manager import get_shell_session_manager

        # Fetch container
        container_result = await db.execute(
            select(Container)
            .where(Container.id == UUID(container_id))
            .where(Container.project_id == project_id)
        )
        container = container_result.scalar_one_or_none()

        if not container:
            return error_output(
                message=f"Container {container_id} not found",
                suggestion="Check the container_id"
            )

        command = params.get("command", "/bin/sh")
        container_name = container.directory or container.name

        # Create shell session
        session_manager = get_shell_session_manager()
        session_info = await session_manager.create_session(
            user_id=user_id,
            project_id=project_id,
            db=db,
            command=command,
            container_name=container_name,
        )

        return success_output(
            message=f"Opened shell session in container '{container.name}'",
            session_id=session_info["session_id"],
            container_id=str(container.id),
            container_name=container.name,
            command=command
        )

    except ValueError as e:
        # Session limit reached
        return error_output(
            message=str(e),
            suggestion="Close existing sessions or use an existing session_id"
        )
    except Exception as e:
        logger.error(f"Failed to open shell: {e}", exc_info=True)
        return error_output(
            message=f"Failed to open shell: {str(e)}",
            suggestion="Check if the container is running"
        )


async def graph_shell_exec_executor(
    params: Dict[str, Any],
    context: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Execute a command in a specific container.

    This is a convenience tool that either uses an existing session
    or creates a one-shot execution in the container.

    Args:
        params: {
            "container_id": "uuid",
            "command": "npm install",
            "timeout": 120 (optional)
        }
        context: Execution context

    Returns:
        Command output
    """
    container_id = params.get("container_id")
    command = params.get("command")

    if not container_id:
        return error_output(
            message="container_id is required",
            suggestion="Provide the UUID of the container"
        )

    if not command:
        return error_output(
            message="command is required",
            suggestion="Provide the command to execute"
        )

    db = context.get("db")
    user_id = context.get("user_id")
    project_id = context.get("project_id")
    project_slug = context.get("project_slug")

    if not db or not user_id or not project_id:
        return error_output(
            message="Missing required context",
            suggestion="Ensure db, user_id, and project_id are in context"
        )

    try:
        from sqlalchemy import select
        from ....models import Container
        from ....services.orchestration import get_orchestrator

        # Fetch container
        container_result = await db.execute(
            select(Container)
            .where(Container.id == UUID(container_id))
            .where(Container.project_id == project_id)
        )
        container = container_result.scalar_one_or_none()

        if not container:
            return error_output(
                message=f"Container {container_id} not found",
                suggestion="Check the container_id"
            )

        timeout = params.get("timeout", 120)
        container_name = container.directory or container.name

        # Use orchestrator to execute command
        orchestrator = get_orchestrator()
        result = await orchestrator.execute_command(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            command=command if isinstance(command, list) else command.split(),
            timeout=timeout,
            working_dir=None
        )

        if result.get("success"):
            return success_output(
                message=f"Executed command in '{container.name}'",
                container_id=str(container.id),
                container_name=container.name,
                output=result.get("output", ""),
                exit_code=result.get("exit_code", 0)
            )
        else:
            return error_output(
                message=f"Command failed: {result.get('error', 'Unknown error')}",
                suggestion="Check the command syntax and container state",
                output=result.get("output", "")
            )

    except Exception as e:
        logger.error(f"Failed to execute command: {e}", exc_info=True)
        return error_output(
            message=f"Failed to execute command: {str(e)}",
            suggestion="Check if the container is running"
        )


async def graph_shell_close_executor(
    params: Dict[str, Any],
    context: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Close a shell session.

    Args:
        params: {
            "session_id": "session-uuid"
        }
        context: Execution context

    Returns:
        Success/error output
    """
    session_id = params.get("session_id")
    if not session_id:
        return error_output(
            message="session_id is required",
            suggestion="Provide the session_id from graph_shell_open"
        )

    db = context.get("db")

    if not db:
        return error_output(
            message="Missing required context",
            suggestion="Ensure db is in context"
        )

    try:
        from ....services.shell_session_manager import get_shell_session_manager

        session_manager = get_shell_session_manager()
        await session_manager.close_session(session_id, db)

        return success_output(
            message=f"Closed shell session {session_id}",
            session_id=session_id
        )

    except Exception as e:
        logger.error(f"Failed to close shell: {e}", exc_info=True)
        return error_output(
            message=f"Failed to close shell: {str(e)}",
            suggestion="Check the session_id"
        )


# Tool definitions
SHELL_TOOLS: List[Tool] = [
    Tool(
        name="graph_shell_open",
        description="Open an interactive shell session in a specific container. Returns session_id for subsequent operations.",
        category=ToolCategory.SHELL,
        parameters={
            "type": "object",
            "properties": {
                "container_id": {
                    "type": "string",
                    "description": "UUID of the container to connect to"
                },
                "command": {
                    "type": "string",
                    "description": "Shell command to run (default: /bin/sh)"
                }
            },
            "required": ["container_id"]
        },
        executor=graph_shell_open_executor,
        examples=[
            '{"tool_name": "graph_shell_open", "parameters": {"container_id": "abc-123"}}'
        ]
    ),
    Tool(
        name="graph_shell_exec",
        description="Execute a command in a specific container. Use for one-off commands without managing sessions.",
        category=ToolCategory.SHELL,
        parameters={
            "type": "object",
            "properties": {
                "container_id": {
                    "type": "string",
                    "description": "UUID of the container to execute in"
                },
                "command": {
                    "type": "string",
                    "description": "Command to execute"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 120)"
                }
            },
            "required": ["container_id", "command"]
        },
        executor=graph_shell_exec_executor,
        examples=[
            '{"tool_name": "graph_shell_exec", "parameters": {"container_id": "abc-123", "command": "npm install"}}',
            '{"tool_name": "graph_shell_exec", "parameters": {"container_id": "abc-123", "command": "npm run build", "timeout": 300}}'
        ]
    ),
    Tool(
        name="graph_shell_close",
        description="Close an open shell session.",
        category=ToolCategory.SHELL,
        parameters={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID from graph_shell_open"
                }
            },
            "required": ["session_id"]
        },
        executor=graph_shell_close_executor,
        examples=[
            '{"tool_name": "graph_shell_close", "parameters": {"session_id": "sess-abc-123"}}'
        ]
    ),
]
