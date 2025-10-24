"""
Shell Command Execution Tools

Tools for executing shell commands in user development environments.
Deployment-aware: supports both Docker and Kubernetes modes.
Uses the command validator and agent API for secure execution.
"""

import logging
import subprocess
from typing import Dict, Any
from .registry import Tool, ToolRegistry, ToolCategory
from ...config import get_settings
from ...services.command_validator import get_command_validator
from .output_formatter import success_output, error_output, pluralize

logger = logging.getLogger(__name__)


async def execute_command_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a shell command in the user's development environment.

    Deployment-aware:
    - Docker mode: Executes via docker exec in the dev container
    - Kubernetes mode: Executes via K8s API in the pod

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
    settings = get_settings()

    # Validate command
    validator = get_command_validator(allow_network=False)
    validation = validator.validate(command, working_dir)

    if not validation.is_valid:
        return error_output(
            message=f"Cannot execute command: {validation.reason}",
            suggestion="Avoid dangerous commands. Use file operations tools like delete_file instead of rm commands",
            command=command,
            details={"risk_level": validation.risk_level.value}
        )

    try:
        if settings.deployment_mode == "kubernetes":
            # Kubernetes mode: Execute in pod
            from ...k8s_client import get_k8s_manager
            k8s_manager = get_k8s_manager()

            output = await k8s_manager.execute_command_in_pod(
                user_id=user_id,
                project_id=project_id,
                command=validation.sanitized_command,
                timeout=timeout
            )

            return success_output(
                message=f"Executed '{command}' successfully",
                command=command,
                stdout=output,
                details={"risk_level": validation.risk_level.value}
            )
        else:
            # Docker mode: Execute via docker exec using container manager
            from ...dev_server_manager import get_container_manager
            container_manager = get_container_manager()

            # Get container name using slug from container tracking
            project_key = f"user-{user_id}-project-{project_id}"
            container_info = container_manager.containers.get(project_key)

            if not container_info:
                # Try to find by labels as fallback
                import subprocess as sp
                result = sp.run(
                    ["docker", "ps", "--filter", f"label=com.tesslate.devserver.project_id={project_id}",
                     "--filter", f"label=com.tesslate.devserver.user_id={user_id}", "--format", "{{.Names}}"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    container_name = result.stdout.strip().split('\n')[0]
                else:
                    raise Exception(f"Container not found for project {project_id}")
            else:
                container_name = container_info["container_name"]

            # Construct docker exec command with proper working directory
            # Note: Docker exec handles shell wrapping differently than K8s,
            # so we use the original command instead of validation.sanitized_command
            working_path = f"/app/{working_dir}" if working_dir != "." else "/app"
            docker_cmd = [
                "docker", "exec",
                "-w", working_path,
                container_name,
                "sh", "-c", command  # Use original command, not sanitized (which is a list)
            ]

            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            if result.returncode == 0:
                return success_output(
                    message=f"Executed '{command}' successfully",
                    command=command,
                    stdout=result.stdout,
                    details={"risk_level": validation.risk_level.value}
                )
            else:
                return error_output(
                    message=f"Command '{command}' failed",
                    suggestion="Check the error output below for details",
                    command=command,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    details={
                        "exit_code": result.returncode,
                        "risk_level": validation.risk_level.value
                    }
                )

    except subprocess.TimeoutExpired:
        return error_output(
            message=f"Command '{command}' timed out after {timeout} seconds",
            suggestion="The command may be hanging or taking too long. Try increasing the timeout or simplifying the command",
            command=command,
            details={"timeout": timeout}
        )
    except Exception as e:
        return error_output(
            message=f"Error executing '{command}': {str(e)}",
            suggestion="Check if the development environment is running",
            command=command,
            details={"error": str(e)}
        )


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

    # Create user-friendly message
    if failed == 0:
        message = f"All {pluralize(successful, 'command')} completed successfully"
    elif successful == 0:
        message = f"All {pluralize(len(results), 'command')} failed"
    else:
        message = f"Executed {len(results)} commands: {successful} succeeded, {failed} failed"

    # Remove "index" from individual results for cleaner output
    clean_results = []
    for r in results:
        result_copy = {k: v for k, v in r.items() if k != "index"}
        clean_results.append(result_copy)

    return success_output(
        message=message,
        results=clean_results,
        details={
            "total_commands": len(commands),
            "executed": len(results),
            "successful": successful,
            "failed": failed
        }
    )


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
