"""
Shell Command Execution Tools

Tools for executing shell commands in user development pods.
Uses the command validator and agent API for secure execution.
"""

import logging
from typing import Dict, Any
from .registry import Tool, ToolRegistry, ToolCategory
from ...k8s_client import get_k8s_manager
from ...services.command_validator import get_command_validator

logger = logging.getLogger(__name__)


async def execute_command_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a shell command in the user's development pod.

    Uses command validation for security.

    Args:
        params: {
            command: str,
            working_dir: str (optional, default "."),
            timeout: int (optional, default 60)
        }
        context: {user_id: int, project_id: str, db: AsyncSession}

    Returns:
        Dict with command output
    """
    command = params.get("command")
    working_dir = params.get("working_dir", ".")
    timeout = params.get("timeout", 60)

    if not command:
        raise ValueError("command parameter is required")

    user_id = context["user_id"]
    project_id = str(context["project_id"])

    # Validate command
    validator = get_command_validator(allow_network=False)
    validation = validator.validate(command, working_dir)

    if not validation.is_valid:
        return {
            "success": False,
            "error": f"Command validation failed: {validation.reason}",
            "risk_level": validation.risk_level.value
        }

    # Execute command
    k8s_manager = get_k8s_manager()

    try:
        output = await k8s_manager.execute_command_in_pod(
            user_id=user_id,
            project_id=project_id,
            command=validation.sanitized_command,
            timeout=timeout
        )

        return {
            "success": True,
            "command": command,
            "stdout": output,
            "risk_level": validation.risk_level.value,
            "message": "Command executed successfully"
        }

    except Exception as e:
        return {
            "success": False,
            "command": command,
            "error": str(e),
            "risk_level": validation.risk_level.value
        }


async def execute_multiple_commands_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute multiple shell commands in sequence.

    Stops on first failure unless continue_on_error is True.

    Args:
        params: {
            commands: List[str],
            working_dir: str (optional),
            continue_on_error: bool (optional, default False)
        }
        context: {user_id: int, project_id: str, db: AsyncSession}

    Returns:
        Dict with results for each command
    """
    commands = params.get("commands", [])
    working_dir = params.get("working_dir", ".")
    continue_on_error = params.get("continue_on_error", False)

    if not commands:
        raise ValueError("commands parameter is required and must be a non-empty list")

    if not isinstance(commands, list):
        raise ValueError("commands must be a list of strings")

    results = []
    for i, command in enumerate(commands):
        logger.info(f"Executing command {i+1}/{len(commands)}: {command}")

        result = await execute_command_tool(
            {"command": command, "working_dir": working_dir},
            context
        )

        results.append({
            "index": i,
            "command": command,
            **result
        })

        # Stop on failure unless continue_on_error is True
        if not result["success"] and not continue_on_error:
            logger.warning(f"Command {i+1} failed, stopping execution")
            break

    successful = sum(1 for r in results if r["success"])
    failed = len(results) - successful

    return {
        "total_commands": len(commands),
        "executed": len(results),
        "successful": successful,
        "failed": failed,
        "results": results
    }


def register_tools(registry: ToolRegistry):
    """Register all command execution tools."""

    registry.register(Tool(
        name="execute_command",
        description="Execute a shell command in the development environment (npm, git, build commands, etc.)",
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute (e.g., 'npm install', 'npm run build')"
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory relative to project root (default: '.')",
                    "default": "."
                },
                "timeout": {
                    "type": "integer",
                    "description": "Command timeout in seconds (default: 60)",
                    "default": 60
                }
            },
            "required": ["command"]
        },
        executor=execute_command_tool,
        category=ToolCategory.SHELL,
        examples=[
            '<tool_call><tool_name>execute_command</tool_name><parameters>{"command": "npm install"}</parameters></tool_call>',
            '<tool_call><tool_name>execute_command</tool_name><parameters>{"command": "npm run build", "timeout": 120}</parameters></tool_call>',
            '<tool_call><tool_name>execute_command</tool_name><parameters>{"command": "ls -la", "working_dir": "src"}</parameters></tool_call>'
        ]
    ))

    registry.register(Tool(
        name="execute_multiple",
        description="Execute multiple shell commands in sequence (useful for setup scripts)",
        parameters={
            "type": "object",
            "properties": {
                "commands": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of commands to execute in order"
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory for all commands",
                    "default": "."
                },
                "continue_on_error": {
                    "type": "boolean",
                    "description": "Continue executing if a command fails (default: false)",
                    "default": False
                }
            },
            "required": ["commands"]
        },
        executor=execute_multiple_commands_tool,
        category=ToolCategory.SHELL,
        examples=[
            '<tool_call><tool_name>execute_multiple</tool_name><parameters>{"commands": ["npm install", "npm run build", "npm test"]}</parameters></tool_call>'
        ]
    ))

    logger.info("Registered 2 command execution tools")
