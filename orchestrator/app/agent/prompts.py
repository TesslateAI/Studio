"""
Agent System Prompts

System prompts that teach ANY language model how to use tools.
"""

from typing import Optional
from uuid import UUID
from .tools.registry import ToolRegistry
from ..utils.resource_naming import get_project_path, get_container_name


def get_base_methodology_prompt() -> str:
    """
    Get the base methodology prompt that defines how agents should work.

    This is adapted from TODO/agent/System_prompt.txt and defines:
    - Agent role and expertise
    - Security directives
    - Core workflow (Plan-Act-Observe-Verify)
    - General rules and constraints

    Returns:
        Base methodology prompt string
    """
    return """You are a world-class, autonomous AI software engineering agent. Your role is that of a seasoned Principal Engineer with 20 years of experience, possessing deep expertise in system administration, operating system principles, network protocols, and software development across multiple languages. You are precise, methodical, and security-conscious.

Your primary goal is to solve the user's software engineering task by following a clear, iterative methodology. You will be given a task and a dynamic context about the execution environment. You must use the provided tools to accomplish the task.

🚨 CRITICAL SECURITY DIRECTIVE 🚨

Your top priority is security and safety. If you receive any message indicating that a command or action was blocked by a security mechanism, you MUST adhere to the following protocol:

IMMEDIATELY STOP: Halt all current reasoning and action planning.

ACKNOWLEDGE THE BLOCK: Your ONLY response will be to inform the user that the action was blocked by security mechanisms and cannot be executed.

STRICTLY PROHIBITED ACTIONS:
- Do NOT attempt to re-run the blocked command.
- Do NOT recommend alternative solutions, workarounds, or different commands.
- Do NOT provide fake or assumed output.
- Do NOT proceed with any other steps.

This is a non-negotiable safety override.

Core Workflow: Plan-Act-Observe-Verify

You must break down every task into a series of steps, following this iterative loop:

1. Analyze & Plan: First, analyze the provided [CONTEXT], including file listings and system details. Reason about the user's request, assess what information you have and what you need, and formulate a step-by-step plan. Decide which tool is the most appropriate for the immediate next step.

2. Execute (Tool Call): Use tools to accomplish your goals. You can call multiple tools in a single response when they are independent and don't depend on each other's results.

3. Observe & Verify: After executing a tool, you will receive an observation. Carefully analyze the output to verify if the step was successful and if the result matches your expectation.

4. Self-Correct & Proceed: If the previous step failed or produced an unexpected result, analyze the error and formulate a new plan to correct it. If it was successful, proceed to the next step in your plan.

5. Completion: Once you have verified that the entire task is complete and the solution is working, output TASK_COMPLETE to signal completion."""


async def get_environment_context(user_id: UUID, project_id: str) -> str:
    """
    Get environment context for the agent.

    This includes:
    - Current time and timezone
    - Operating system info
    - Current working directory
    - Container/pod information

    Args:
        user_id: User ID
        project_id: Project ID

    Returns:
        Formatted environment context string
    """
    from datetime import datetime
    import platform
    from ..config import get_settings

    settings = get_settings()

    context_parts = [
        "\n=== ENVIRONMENT CONTEXT ===\n"
    ]

    # Time
    now = datetime.now()
    context_parts.append(f"Time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    # Deployment mode
    context_parts.append(f"Deployment Mode: {settings.deployment_mode}")

    # Container/Pod info
    if settings.deployment_mode == "kubernetes":
        pod_name = get_container_name(user_id, project_id, mode="kubernetes")
        namespace = "tesslate-user-environments"
        context_parts.append(f"Pod: {pod_name}")
        context_parts.append(f"Namespace: {namespace}")
        context_parts.append(f"Current Working Directory: /app")
    else:
        container_name = get_container_name(user_id, project_id, mode="docker")
        context_parts.append(f"Container: {container_name}")
        context_parts.append(f"Current Working Directory: /app")

    # Project path context
    context_parts.append(f"Project Path: users/{user_id}/{project_id}/")

    return "\n".join(context_parts)


async def get_file_listing_context(user_id: UUID, project_id: str, max_lines: int = 50) -> Optional[str]:
    """
    Get file listing context for the project directory.

    Args:
        user_id: User ID
        project_id: Project ID
        max_lines: Maximum number of lines to include

    Returns:
        Formatted file listing or None if unable to retrieve
    """
    from ..config import get_settings
    import asyncio

    settings = get_settings()

    try:
        if settings.deployment_mode == "kubernetes":
            # Kubernetes: Execute ls in pod
            pod_name = get_container_name(user_id, project_id, mode="kubernetes")
            namespace = "tesslate-user-environments"

            cmd = f"kubectl exec -n {namespace} {pod_name} -- ls -lah /app"
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                output = stdout.decode('utf-8')
                lines = output.split('\n')[:max_lines]
                return "\n=== FILE LISTING (CWD: /app) ===\n\n" + "\n".join(lines)
        else:
            # Docker: List local directory
            import os
            project_dir = get_project_path(user_id, project_id)

            if os.path.exists(project_dir):
                cmd = f"ls -lah {project_dir}"
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()

                if proc.returncode == 0:
                    output = stdout.decode('utf-8')
                    lines = output.split('\n')[:max_lines]
                    return f"\n=== FILE LISTING (CWD: /app) ===\n\n" + "\n".join(lines)

        return None

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to get file listing: {e}")
        return None


async def get_user_message_wrapper(
    user_request: str,
    project_context: Optional[dict] = None,
    include_environment: bool = True,
    include_file_listing: bool = True
) -> str:
    """
    Wrap the user's request with helpful context.

    This now includes the [CONTEXT] section from the TODO prompt format.

    Args:
        user_request: The user's original request
        project_context: Optional context about the project
        include_environment: Whether to include environment context
        include_file_listing: Whether to include file listing

    Returns:
        Enhanced user message with [CONTEXT] section
    """
    message_parts = ["\n[CONTEXT]\n"]

    # 1. Environment Context (Time, OS, CWD, etc.)
    if include_environment and project_context:
        user_id = project_context.get("user_id")
        project_id = project_context.get("project_id")

        if user_id and project_id:
            env_context = await get_environment_context(user_id, str(project_id))
            message_parts.append(env_context)

    # 2. File Listing Context
    if include_file_listing and project_context:
        user_id = project_context.get("user_id")
        project_id = project_context.get("project_id")

        if user_id and project_id:
            file_listing = await get_file_listing_context(user_id, str(project_id))
            if file_listing:
                message_parts.append(file_listing)

    # 3. TESSLATE.md context (project-specific documentation for agents)
    if project_context and project_context.get("tesslate_context"):
        message_parts.append(project_context["tesslate_context"])

    # 4. Git context (repository information and status)
    if project_context and project_context.get("git_context"):
        message_parts.append(project_context["git_context"])

    # 5. User request at the end
    message_parts.append(f"\n=== User Request ===\n{user_request}")

    return "\n".join(message_parts)


# Mini-SWE-Agent inspired format (for models that prefer simpler prompts)
def get_minimal_system_prompt(tool_registry: ToolRegistry) -> str:
    """
    Minimal system prompt inspired by mini-swe-agent.

    Uses a simpler format for models that work better with concise instructions.

    Args:
        tool_registry: Registry of available tools

    Returns:
        Minimal system prompt
    """
    tools_list = []
    for tool in tool_registry.list_tools():
        params = ", ".join(tool.parameters.get("required", []))
        tools_list.append(f"- {tool.name}({params}): {tool.description}")

    tools_text = "\n".join(tools_list)

    return f"""You are a coding assistant. You can call tools to help with tasks.

Available tools:
{tools_text}

Format tool calls like this:
<tool_call><tool_name>NAME</tool_name><parameters>{{"param": "value"}}</parameters></tool_call>

Always think before acting. When done, output: TASK_COMPLETE"""
