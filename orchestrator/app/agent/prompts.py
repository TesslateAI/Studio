"""
Agent System Prompts

System prompts that teach ANY language model how to use tools.
"""

from typing import Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from .tools.registry import ToolRegistry
from ..utils.resource_naming import get_project_path, get_container_name


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
    from ..services.orchestration import is_kubernetes_mode, get_deployment_mode

    context_parts = [
        "\n=== ENVIRONMENT CONTEXT ===\n"
    ]

    # Time
    now = datetime.now()
    context_parts.append(f"Time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    # Deployment mode
    deployment_mode = get_deployment_mode()
    context_parts.append(f"Deployment Mode: {deployment_mode.value}")

    # Container/Pod info
    if is_kubernetes_mode():
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
    from ..services.orchestration import is_kubernetes_mode
    import asyncio

    try:
        if is_kubernetes_mode():
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


def get_mode_instructions(mode: str) -> str:
    """
    Get mode-specific instructions for the agent.

    Args:
        mode: Edit mode ('allow', 'ask', 'plan')

    Returns:
        Instructions text for the given mode
    """
    if mode == 'plan':
        return """
[PLAN MODE ACTIVE]
You are in read-only planning mode. You MUST NOT execute any file modifications or shell commands.
Instead, create a detailed markdown plan explaining what changes you would make.
All read operations (read_file, get_project_info, etc.) are allowed and encouraged for gathering context.
Format your plan clearly with headings, bullet points, and code examples where helpful.
"""
    elif mode == 'ask':
        return """
[ASK BEFORE EDIT MODE]
You can propose file modifications and shell commands, but they require user approval.
The user will be prompted to approve each dangerous operation before execution.
Read operations proceed without approval.
"""
    else:  # allow
        return """
[FULL EDIT MODE]
You have full access to all tools including file modifications and shell commands.
Execute changes directly as needed to accomplish the user's goals.
"""


def substitute_markers(
    system_prompt: str,
    context: Dict[str, Any],
    tool_names: Optional[list] = None
) -> str:
    """
    Substitute {marker} placeholders in system prompts with actual runtime values.

    This allows agent system prompts to include dynamic content that changes based
    on the current execution context (edit mode, project info, etc.).

    Available markers:
        {mode} - Current edit mode ('allow', 'ask', 'plan')
        {mode_instructions} - Detailed instructions for the current mode
        {project_name} - Name of the current project
        {project_description} - Description of the current project
        {timestamp} - Current ISO timestamp
        {user_name} - User's name (if available)
        {project_path} - Project directory path
        {git_branch} - Current git branch (if available)
        {tool_list} - Comma-separated list of available tools

    Args:
        system_prompt: The agent's system prompt with {marker} placeholders
        context: Execution context dict with user_id, project_id, edit_mode, etc.
        tool_names: Optional list of tool names available to the agent

    Returns:
        System prompt with markers replaced by actual values

    Example:
        >>> prompt = "You are in {mode} mode. {mode_instructions} Project: {project_name}"
        >>> result = substitute_markers(prompt, {"edit_mode": "plan", "project_context": {"project_name": "MyApp"}})
        >>> print(result)
        You are in plan mode. [PLAN MODE ACTIVE]... Project: MyApp
    """
    # Extract values from context
    edit_mode = context.get('edit_mode', 'allow')
    project_context = context.get('project_context', {})

    # Build marker replacement map
    markers = {
        'mode': edit_mode,
        'mode_instructions': get_mode_instructions(edit_mode),
        'project_name': project_context.get('project_name', 'Unknown Project'),
        'project_description': project_context.get('project_description', ''),
        'timestamp': datetime.now().isoformat(),
        'user_name': context.get('user_name', ''),
        'project_path': f"/app",  # Standard container path
        'git_branch': project_context.get('git_context', {}).get('branch', ''),
        'tool_list': ', '.join(tool_names) if tool_names else '',
    }

    # Replace each {marker} with its value
    result = system_prompt
    for marker, value in markers.items():
        placeholder = f'{{{marker}}}'
        if placeholder in result:
            result = result.replace(placeholder, str(value))

    return result


