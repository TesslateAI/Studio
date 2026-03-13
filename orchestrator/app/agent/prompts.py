"""
Agent System Prompts

System prompts that teach ANY language model how to use tools.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from ..utils.resource_naming import get_container_name, get_project_path


async def get_environment_context(
    user_id: UUID, project_id: str, container_directory: str | None = None
) -> str:
    """
    Get environment context for the agent.

    This includes:
    - Current time and timezone
    - Operating system info
    - Current working directory
    - Container/pod information
    - Container directory (subdirectory scope for file operations)

    Args:
        user_id: User ID
        project_id: Project ID
        container_directory: Optional subdirectory for container-scoped file operations

    Returns:
        Formatted environment context string
    """
    from datetime import datetime

    from ..services.orchestration import get_deployment_mode, is_kubernetes_mode

    context_parts = ["\n=== ENVIRONMENT CONTEXT ===\n"]

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
        context_parts.append("Current Working Directory: /app")
    else:
        container_name = get_container_name(user_id, project_id, mode="docker")
        context_parts.append(f"Container: {container_name}")
        context_parts.append("Current Working Directory: /app")

    # Container directory scope — file tools auto-resolve paths relative to this
    if container_directory and container_directory != ".":
        context_parts.append(f"Container Directory: {container_directory}")
        context_parts.append(
            f"File Scope: File tools (read_file, write_file, patch_file) automatically resolve "
            f"paths relative to /app/{container_directory}/. Use paths relative to that directory "
            f"(e.g., 'app/page.tsx' resolves to '/app/{container_directory}/app/page.tsx'). "
            f"For bash_exec, the working directory is /app — use 'cd {container_directory} && ...' "
            f"or full paths like '/app/{container_directory}/...'."
        )
    else:
        context_parts.append("Container Directory: . (project root)")
        context_parts.append(
            "File Scope: File tools resolve paths relative to /app/."
        )

    # Project path context
    context_parts.append(f"Project Path: users/{user_id}/{project_id}/")

    return "\n".join(context_parts)


async def get_file_listing_context(
    user_id: UUID, project_id: str, max_lines: int = 50
) -> str | None:
    """
    Get file listing context for the project directory.

    Args:
        user_id: User ID
        project_id: Project ID
        max_lines: Maximum number of lines to include

    Returns:
        Formatted file listing or None if unable to retrieve
    """
    import asyncio

    from ..services.orchestration import is_kubernetes_mode

    try:
        if is_kubernetes_mode():
            # Kubernetes: Execute ls in pod
            pod_name = get_container_name(user_id, project_id, mode="kubernetes")
            namespace = "tesslate-user-environments"

            cmd = f"kubectl exec -n {namespace} {pod_name} -- ls -lah /app"
            proc = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                output = stdout.decode("utf-8")
                lines = output.split("\n")[:max_lines]
                return "\n=== FILE LISTING (CWD: /app) ===\n\n" + "\n".join(lines)
        else:
            # Docker: List local directory
            import os

            project_dir = get_project_path(user_id, project_id)

            if os.path.exists(project_dir):
                cmd = f"ls -lah {project_dir}"
                proc = await asyncio.create_subprocess_shell(
                    cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()

                if proc.returncode == 0:
                    output = stdout.decode("utf-8")
                    lines = output.split("\n")[:max_lines]
                    return "\n=== FILE LISTING (CWD: /app) ===\n\n" + "\n".join(lines)

        return None

    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to get file listing: {e}")
        return None


async def get_user_message_wrapper(
    user_request: str,
    project_context: dict | None = None,
    include_environment: bool = True,
    include_file_listing: bool = True,
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
        container_directory = project_context.get("container_directory")

        if user_id and project_id:
            env_context = await get_environment_context(
                user_id, str(project_id), container_directory=container_directory
            )
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
        git_ctx = project_context["git_context"]
        if isinstance(git_ctx, dict):
            message_parts.append(git_ctx.get("formatted", ""))
        else:
            message_parts.append(git_ctx)

    # 4.5 Skills catalog (progressive disclosure — names + descriptions only)
    if project_context and project_context.get("available_skills"):
        skills_section = render_skills_catalog(project_context["available_skills"])
        if skills_section:
            message_parts.append(skills_section)

    # 5. User request at the end
    message_parts.append(f"\n=== User Request ===\n{user_request}")

    return "\n".join(message_parts)


def render_skills_catalog(skills) -> str:
    """
    Render available skills as a compact catalog for injection into the system prompt.

    Progressive disclosure: only name + description (~20 tokens per skill).
    Full instructions loaded on-demand via load_skill tool.
    """
    if not skills:
        return ""
    lines = ["\n=== AVAILABLE SKILLS ==="]
    lines.append("Use the load_skill tool when a task matches a skill's description.")
    for s in skills:
        if hasattr(s, "source"):
            tag = "(installed)" if s.source == "db" else f"(project: {s.file_path})"
        else:
            tag = ""
        lines.append(f"- {s.name}: {s.description} {tag}")
    lines.append("=== END SKILLS ===")
    return "\n".join(lines)


def get_mode_instructions(mode: str) -> str:
    """
    Get mode-specific instructions for the agent.

    Args:
        mode: Edit mode ('allow', 'ask', 'plan')

    Returns:
        Instructions text for the given mode
    """
    if mode == "plan":
        return """
[PLAN MODE ACTIVE]
You are in planning mode. You MUST NOT execute any file modifications (write_file, patch_file, etc.).
Shell commands (bash_exec) ARE allowed for context gathering — use them to explore files, check dependencies, run ls/grep/find, etc.
Create a detailed markdown plan explaining what changes you would make.
All read operations (read_file, get_project_info, etc.) are allowed and encouraged for gathering context.
Format your plan clearly with headings, bullet points, and code examples where helpful.
"""
    elif mode == "ask":
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
    system_prompt: str, context: dict[str, Any], tool_names: list | None = None
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
    edit_mode = context.get("edit_mode", "allow")
    project_context = context.get("project_context", {})

    # Build marker replacement map
    markers = {
        "mode": edit_mode,
        "mode_instructions": get_mode_instructions(edit_mode),
        "project_name": project_context.get("project_name", "Unknown Project"),
        "project_description": project_context.get("project_description", ""),
        "timestamp": datetime.now().isoformat(),
        "user_name": context.get("user_name", ""),
        "project_path": "/app",  # Standard container path
        "git_branch": project_context.get("git_context", {}).get("branch", "")
        if isinstance(project_context.get("git_context"), dict)
        else "",
        "tool_list": ", ".join(tool_names) if tool_names else "",
    }

    # Replace each {marker} with its value
    result = system_prompt
    for marker, value in markers.items():
        placeholder = f"{{{marker}}}"
        if placeholder in result:
            result = result.replace(placeholder, str(value))

    return result
