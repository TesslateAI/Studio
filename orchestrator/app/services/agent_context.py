"""
Context builder functions for the AI agent chat system.

Extracted from routers/chat.py to allow reuse across chat endpoints,
worker tasks, and reconnect flows.
"""

import logging
import os
from uuid import UUID

import aiofiles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import (
    AgentStep,
    Chat,
    Container,
    ContainerConnection,
    GitRepository,
    Message,
    Project,
)
from ..utils.resource_naming import get_project_path

settings = get_settings()
logger = logging.getLogger(__name__)


def _resolve_container_name(container) -> str | None:
    """Resolve a container's service name using same logic as K8s orchestrator.

    When directory is "." (root), uses sanitized container.name instead.
    Returns DNS-1123 compliant name matching K8s label values.
    """
    if not container:
        return None
    dir_for_name = (
        container.name
        if container.directory in (".", "", None)
        else container.directory
    )
    safe = dir_for_name.lower().replace(" ", "-").replace("_", "-").replace(".", "-")
    return "".join(c for c in safe if c.isalnum() or c == "-")


async def _build_git_context(project: Project, user_id: UUID, db: AsyncSession) -> dict | None:
    """
    Build Git context for agent if project has a Git repository connected.

    Returns a dict with structured git info, or None if no Git repo.
    Keys:
        - "formatted": Human-readable string for user message context
        - "branch": Current branch name (for {git_branch} marker)
        - "repo_url": Repository URL
        - "auto_push": Whether auto-push is enabled
    """
    try:
        from .git_manager import GitManager

        # Check if project has Git repository
        result = await db.execute(
            select(GitRepository).where(GitRepository.project_id == project.id)
        )
        git_repo = result.scalar_one_or_none()

        if not git_repo:
            return None

        # Get current Git status
        git_manager = GitManager(user_id=user_id, project_id=str(project.id))
        try:
            git_status = await git_manager.get_status()
        except Exception as status_error:
            logger.warning(f"[GIT-CONTEXT] Could not get Git status: {status_error}")
            git_status = None

        # Build concise Git context
        context_lines = [
            "\n=== Git Repository ===",
            f"Repository: {git_repo.repo_url}",
        ]

        branch = ""
        if git_status:
            branch = git_status.get("branch", "")
            context_lines.append(f"Branch: {branch}")

            total_changes = (
                git_status.get("staged_count", 0)
                + git_status.get("unstaged_count", 0)
                + git_status.get("untracked_count", 0)
            )
            if total_changes > 0:
                context_lines.append(f"Uncommitted Changes: {total_changes}")

            sync_info = []
            if git_status.get("ahead", 0) > 0:
                sync_info.append(f"{git_status['ahead']} ahead")
            if git_status.get("behind", 0) > 0:
                sync_info.append(f"{git_status['behind']} behind")
            if sync_info:
                context_lines.append(f"Remote: {', '.join(sync_info)}")

            if git_status.get("last_commit"):
                last_commit = git_status["last_commit"]
                context_lines.append(
                    f"Last Commit: {last_commit['message']} ({last_commit['sha'][:8]})"
                )

        if git_repo.auto_push:
            context_lines.append("Auto-push: ENABLED")
        else:
            context_lines.append("Auto-push: DISABLED")

        return {
            "formatted": "\n".join(context_lines),
            "branch": branch,
            "repo_url": git_repo.repo_url,
            "auto_push": git_repo.auto_push,
        }

    except Exception as e:
        logger.error(f"[GIT-CONTEXT] Failed to build Git context: {e}", exc_info=True)
        return None


async def _build_architecture_context(project: Project, db: AsyncSession) -> str | None:
    """
    Build architecture context describing containers, connections, and
    auto-injected environment variables so the agent knows what services
    are available and which env vars it can use in code.
    """
    try:
        from .secret_manager_env import (
            get_injected_env_vars_for_container,
        )

        # Fetch containers
        result = await db.execute(select(Container).where(Container.project_id == project.id))
        containers = result.scalars().all()
        if not containers:
            return None

        # Fetch connections
        conn_result = await db.execute(
            select(ContainerConnection).where(ContainerConnection.project_id == project.id)
        )
        connections = conn_result.scalars().all()

        # Build container lookup
        container_map = {str(c.id): c for c in containers}

        lines = ["\n=== Project Architecture ==="]

        # List containers
        lines.append("\nContainers:")
        for c in containers:
            svc_label = f" ({c.service_slug})" if c.service_slug else ""
            mode_label = ""
            if c.deployment_mode == "external":
                mode_label = " [external]"
            port_label = f" port:{c.effective_port}"
            lines.append(f"  - {c.name}{svc_label}{mode_label}{port_label} [{c.status}]")

        # List connections
        if connections:
            lines.append("\nConnections:")
            for conn in connections:
                src = container_map.get(str(conn.source_container_id))
                tgt = container_map.get(str(conn.target_container_id))
                if src and tgt:
                    lines.append(f"  - {src.name} -> {tgt.name} ({conn.connector_type})")

        # List injected env vars per container, grouped by source
        has_injected = False
        for c in containers:
            injected = await get_injected_env_vars_for_container(db, c.id, project.id)
            if injected:
                if not has_injected:
                    lines.append("\nAuto-injected environment variables (from connections):")
                    has_injected = True
                # Group by source so multi-source containers read clearly
                by_source: dict[str, list[str]] = {}
                for iv in injected:
                    by_source.setdefault(iv["source_container_name"], []).append(iv["key"])
                for src_name, keys in by_source.items():
                    lines.append(f"  {c.name}: {', '.join(keys)}  (from {src_name})")

        if has_injected:
            lines.append(
                "\nThese env vars are automatically available at runtime — "
                "use them directly in code (e.g. process.env.DATABASE_URL) "
                "without asking the user to configure them."
            )

        return "\n".join(lines)

    except Exception as e:
        logger.error(
            f"[ARCH-CONTEXT] Failed to build architecture context: {e}",
            exc_info=True,
        )
        return None


async def _get_chat_history(
    chat_id: UUID, db: AsyncSession, limit: int = 10
) -> list[dict[str, str]]:
    """
    Fetch recent chat history for context.

    Args:
        chat_id: Chat ID to fetch messages from
        db: Database session
        limit: Maximum number of message pairs to fetch (default 10, max 20)

    Returns:
        List of message dictionaries with 'role' and 'content' keys
    """
    try:
        # Limit to prevent token overflow
        limit = min(limit, 20)

        # Fetch recent messages, excluding the current one (it will be added separately)
        messages_result = await db.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at.desc())
            .limit(limit * 2)  # *2 to account for user+assistant pairs
        )
        messages = list(messages_result.scalars().all())

        # Reverse to get chronological order (oldest first)
        messages.reverse()

        # Format messages for LLM
        formatted_messages = []
        for msg in messages:
            # Skip system messages or empty content
            if not msg.content or msg.role not in ["user", "assistant"]:
                continue

            # For user messages, just add the content
            if msg.role == "user":
                formatted_messages.append({"role": msg.role, "content": msg.content})
            # For assistant messages, check if there are agent iterations in metadata
            elif msg.role == "assistant":
                metadata = msg.message_metadata or {}

                # Resolve steps: prefer AgentStep table rows when flagged,
                # otherwise fall back to inline metadata["steps"].
                steps = []
                if metadata.get("steps_table"):
                    # Steps are stored in the AgentStep table — query them
                    try:
                        steps_result = await db.execute(
                            select(AgentStep)
                            .where(AgentStep.message_id == msg.id)
                            .order_by(AgentStep.step_index)
                        )
                        step_rows = steps_result.scalars().all()
                        steps = [row.step_data for row in step_rows]
                    except Exception as step_err:
                        logger.warning(
                            f"[CHAT-HISTORY] Failed to load AgentStep rows for "
                            f"message {msg.id}: {step_err}"
                        )
                        # Fall back to inline metadata if table query fails
                        steps = metadata.get("steps", [])
                else:
                    steps = metadata.get("steps", [])

                if steps:
                    # Agent message with iterations - reconstruct full conversation
                    # Include each iteration's response as a separate assistant message
                    # to preserve the full context of the agent's thought process
                    for step in steps:
                        # Build a detailed response for each iteration
                        thought = step.get("thought", "")
                        response_text = step.get("response_text", "")
                        tool_calls = step.get("tool_calls", [])

                        iteration_content = ""

                        # Add thought if present
                        if thought:
                            iteration_content += f"THOUGHT: {thought}\n\n"

                        # Add tool calls if present
                        if tool_calls:
                            iteration_content += "Tool Calls:\n"
                            for tc in tool_calls:
                                tool_name = tc.get("name", "unknown")
                                tool_result = tc.get("result", {})
                                success = tool_result.get("success", False)

                                iteration_content += (
                                    f"- {tool_name}: {'✓ Success' if success else '✗ Failed'}\n"
                                )

                                # Add brief result summary
                                if success and tool_result.get("result"):
                                    result_data = tool_result["result"]
                                    if isinstance(result_data, dict):
                                        if "message" in result_data:
                                            iteration_content += f"  {result_data['message']}\n"
                                    else:
                                        iteration_content += f"  {str(result_data)[:200]}\n"

                            iteration_content += "\n"

                        # Add response text
                        if response_text:
                            iteration_content += response_text

                        if iteration_content.strip():
                            formatted_messages.append(
                                {"role": "assistant", "content": iteration_content}
                            )

                            # Add tool results as user feedback (simulating the iterative flow)
                            if tool_calls:
                                tool_results_feedback = "Tool Results:\n"
                                for idx, tc in enumerate(tool_calls):
                                    tool_name = tc.get("name", "unknown")
                                    tool_result = tc.get("result", {})
                                    success = tool_result.get("success", False)

                                    tool_results_feedback += f"\n{idx + 1}. {tool_name}: {'✓ Success' if success else '✗ Failed'}\n"

                                    if tool_result.get("result"):
                                        result_data = tool_result["result"]
                                        if isinstance(result_data, dict):
                                            # Add key result fields
                                            for key in ["message", "content", "stdout", "output"]:
                                                if key in result_data:
                                                    content = str(result_data[key])[
                                                        :500
                                                    ]  # Limit content length
                                                    tool_results_feedback += (
                                                        f"   {key}: {content}\n"
                                                    )
                                                    break
                                        else:
                                            tool_results_feedback += (
                                                f"   {str(result_data)[:500]}\n"
                                            )

                                formatted_messages.append(
                                    {"role": "user", "content": tool_results_feedback}
                                )
                else:
                    # Regular assistant message without iterations
                    formatted_messages.append({"role": msg.role, "content": msg.content})

        logger.info(f"[CHAT-HISTORY] Fetched {len(formatted_messages)} messages for chat {chat_id}")
        return formatted_messages

    except Exception as e:
        logger.error(f"[CHAT-HISTORY] Failed to fetch chat history: {e}", exc_info=True)
        return []


async def _build_tesslate_context(
    project: Project,
    user_id: UUID,
    db: AsyncSession,
    container_name: str | None = None,
    container_directory: str | None = None,
) -> str | None:
    """
    Build TESSLATE.md context for agent.

    Reads TESSLATE.md from the user's project container. For container-scoped agents,
    reads from the container's directory. If it doesn't exist, copies the generic
    template from orchestrator/template/TESSLATE.md.

    Args:
        project: Project model
        user_id: User UUID
        db: Database session
        container_name: Optional container name for multi-container projects
        container_directory: Optional container directory for file path resolution

    Returns the TESSLATE.md content as a formatted string, or None if unable to read.
    """
    try:
        # Read TESSLATE.md from the user's project (deployment-aware)
        tesslate_content = None

        from .orchestration import get_orchestrator, is_kubernetes_mode

        # Try unified orchestrator first
        try:
            orchestrator = get_orchestrator()
            tesslate_content = await orchestrator.read_file(
                user_id=user_id,
                project_id=project.id,
                container_name=container_name,  # Use specific container if provided
                file_path="TESSLATE.md",
                project_slug=project.slug,
                subdir=container_directory,  # Read from container's subdirectory
            )

            # If TESSLATE.md doesn't exist, copy the template
            if tesslate_content is None:
                logger.info(
                    f"[TESSLATE-CONTEXT] TESSLATE.md not found in project {project.id}, copying template"
                )

                # Read the generic template
                template_path = os.path.join(
                    os.path.dirname(__file__), "..", "..", "template", "TESSLATE.md"
                )
                try:
                    async with aiofiles.open(template_path, encoding="utf-8") as f:
                        template_content = await f.read()

                    # Write template to container's subdirectory
                    success = await orchestrator.write_file(
                        user_id=user_id,
                        project_id=project.id,
                        container_name=container_name,
                        file_path="TESSLATE.md",
                        content=template_content,
                        project_slug=project.slug,
                        subdir=container_directory,  # Write to container's subdirectory
                    )

                    if success:
                        tesslate_content = template_content
                        logger.info(
                            f"[TESSLATE-CONTEXT] Successfully copied template to project {project.id}"
                        )
                    else:
                        logger.warning("[TESSLATE-CONTEXT] Failed to write template to container")

                except Exception as e:
                    logger.error(f"[TESSLATE-CONTEXT] Failed to read template file: {e}")

        except Exception as e:
            logger.debug(f"[TESSLATE-CONTEXT] Could not read via orchestrator: {e}")

        # Fallback: Docker mode - read from local filesystem
        if tesslate_content is None and not is_kubernetes_mode():
            # Docker mode: Read from local filesystem
            project_dir = get_project_path(user_id, project.id)
            tesslate_path = os.path.join(project_dir, "TESSLATE.md")

            if os.path.exists(tesslate_path):
                try:
                    async with aiofiles.open(tesslate_path, encoding="utf-8") as f:
                        tesslate_content = await f.read()
                except Exception as e:
                    logger.error(f"[TESSLATE-CONTEXT] Failed to read TESSLATE.md: {e}")
            else:
                # Copy template
                logger.info(
                    f"[TESSLATE-CONTEXT] TESSLATE.md not found in project {project.id}, copying template"
                )
                template_path = os.path.join(
                    os.path.dirname(__file__), "..", "..", "template", "TESSLATE.md"
                )

                try:
                    # Ensure project directory exists
                    os.makedirs(project_dir, exist_ok=True)

                    async with aiofiles.open(template_path, encoding="utf-8") as f:
                        template_content = await f.read()

                    async with aiofiles.open(tesslate_path, "w", encoding="utf-8") as f:
                        await f.write(template_content)

                    tesslate_content = template_content
                    logger.info(
                        f"[TESSLATE-CONTEXT] Successfully copied template to project {project.id}"
                    )

                except Exception as e:
                    logger.error(f"[TESSLATE-CONTEXT] Failed to copy template: {e}")

        if tesslate_content:
            # Return formatted context
            return f"\n=== Project Context (TESSLATE.md) ===\n\n{tesslate_content}\n"
        else:
            return None

    except Exception as e:
        logger.error(f"[TESSLATE-CONTEXT] Failed to build TESSLATE context: {e}", exc_info=True)
        return None
