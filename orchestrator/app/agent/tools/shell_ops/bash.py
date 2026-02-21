"""
Bash Convenience Tool

One-shot command execution using the orchestrator's execute_command method.
Returns immediately when the command exits — no PTY session, no sleep.

Works identically on Docker and Kubernetes (same orchestrator interface).
"""

import logging
from typing import Any
from uuid import UUID

from ..output_formatter import error_output, strip_ansi_codes, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


async def bash_exec_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Execute a single command via the orchestrator's one-shot execute_command.

    Uses asyncio subprocess (Docker) or K8s exec API (Kubernetes) — both return
    immediately on process exit with stdout+stderr combined. No PTY, no sleep.

    Args:
        params: {
            command: str,      # Command to execute
            timeout: int       # Max seconds to wait (default: 120)
        }
        context: {user_id: UUID, project_id: str, db: AsyncSession, container_name: str?}

    Returns:
        Dict with command output and exit code info
    """
    from ....services.orchestration import get_orchestrator

    command = params.get("command")
    timeout = int(params.get("timeout", 120))

    if not command:
        raise ValueError("command parameter is required")

    user_id = context["user_id"]
    project_id = context["project_id"]
    project_slug = context.get("project_slug", "")
    container_name = context.get("container_name")

    logger.info(f"[BASH] Executing (one-shot): {command[:100]}...")

    try:
        orchestrator = get_orchestrator()

        # orchestrator.execute_command expects a raw service/directory name
        # (e.g. "next-js-15") — it builds the full container name internally.
        # When container_name is None (single-container project), resolve the
        # default service name from the running project status.
        if not container_name:
            status = await orchestrator.get_project_status(project_slug, str(project_id))
            containers = status.get("containers", {})
            # Pick the first running service, or first service if none running
            for svc_name, info in containers.items():
                if info.get("running"):
                    container_name = svc_name
                    break
            if not container_name and containers:
                container_name = next(iter(containers.keys()))
            if not container_name:
                raise RuntimeError("No containers found. Please start the project first.")

        logger.info(f"[BASH] Resolved container: {container_name}")

        # The orchestrator's execute_command expects command as a list.
        # Wrap in /bin/sh -c so the shell interprets pipes, redirects, etc.
        cmd_list = ["/bin/sh", "-c", command]

        output = await orchestrator.execute_command(
            user_id=user_id,
            project_id=UUID(str(project_id)) if not isinstance(project_id, UUID) else project_id,
            container_name=container_name,
            command=cmd_list,
            timeout=timeout,
        )

        # Strip ANSI control codes from output
        clean_output = strip_ansi_codes(output) if output else ""

        logger.info(f"[BASH] Command completed, output_length={len(clean_output)}")

        return success_output(
            message=f"Executed '{command}'",
            output=clean_output,
            details={
                "command": command,
                "exit_code": 0,
            },
        )

    except Exception as e:
        error_msg = str(e)
        logger.error(f"[BASH] Command failed: {error_msg}")

        # Distinguish timeout from other errors
        if "timed out" in error_msg.lower() or "timeout" in error_msg.lower():
            return error_output(
                message=f"Command timed out after {timeout}s: {command}",
                suggestion="Try a shorter command or increase the timeout parameter",
                details={"command": command, "timeout": timeout, "error": error_msg},
            )

        return error_output(
            message=f"Command execution failed: {error_msg}",
            suggestion="Check your command syntax and ensure the dev container is running",
            details={"command": command, "error": error_msg},
        )


def register_bash_tools(registry):
    """Register bash convenience tools."""

    registry.register(
        Tool(
            name="bash_exec",
            description="Execute a bash/sh command and return its output. The command runs to completion and returns stdout+stderr. For interactive sessions, use shell_open + shell_exec instead.",
            category=ToolCategory.SHELL,
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Command to execute (e.g., 'npm install', 'ls -la', 'cat package.json')",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Maximum seconds to wait for the command to finish (default: 120)",
                        "default": 120,
                    },
                },
                "required": ["command"],
            },
            executor=bash_exec_tool,
            examples=[
                '{"tool_name": "bash_exec", "parameters": {"command": "npm install"}}',
                '{"tool_name": "bash_exec", "parameters": {"command": "ls -la", "timeout": 30}}',
            ],
        )
    )

    logger.info("Registered 1 bash convenience tool")
