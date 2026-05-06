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
    Container,
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
    dir_for_name = container.name if container.directory in (".", "", None) else container.directory
    safe = dir_for_name.lower().replace(" ", "-").replace("_", "-").replace(".", "-")
    return "".join(c for c in safe if c.isalnum() or c == "-")


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
            return "\n=== Project Context (TESSLATE.md) ===\n\n" + tesslate_content + "\n"
        return None

    except Exception as e:
        logger.error(f"[TESSLATE-CONTEXT] Failed to build TESSLATE context: {e}", exc_info=True)
        return None


async def _build_cross_platform_context(
    chat_id: UUID,
    user_id: UUID,
    project_id: UUID | None,
    platform: str | None,
    db: AsyncSession,
) -> str | None:
    """
    Build a brief summary of the user's recent activity on OTHER platforms.

    Injected into the agent system prompt for gateway-originated tasks so
    the agent has cross-platform awareness without merging conversations.
    """
    if not platform or not project_id:
        return None

    try:
        from datetime import UTC, datetime, timedelta

        from ..models import Chat

        now = datetime.now(UTC)
        result = await db.execute(
            select(Chat)
            .where(
                Chat.user_id == user_id,
                Chat.project_id == project_id,
                Chat.platform.isnot(None),
                Chat.platform != platform,
                Chat.status == "active",
                Chat.last_active_at > now - timedelta(hours=24),
            )
            .order_by(Chat.last_active_at.desc())
            .limit(3)
        )
        other_sessions = result.scalars().all()

        if not other_sessions:
            return None

        lines = ["Recent activity on other platforms:"]
        for session in other_sessions:
            # Fetch last 2 messages from each session
            msgs_result = await db.execute(
                select(Message)
                .where(Message.chat_id == session.id)
                .order_by(Message.created_at.desc())
                .limit(2)
            )
            msgs = list(msgs_result.scalars().all())
            msgs.reverse()

            summary_parts = []
            for msg in msgs:
                role = "User" if msg.role == "user" else "Agent"
                content = (msg.content or "")[:100]
                if len(msg.content or "") > 100:
                    content += "..."
                summary_parts.append(f"{role}: {content}")

            if summary_parts:
                lines.append(f"- [{session.platform}] {' | '.join(summary_parts)}")

        if len(lines) <= 1:
            return None

        return "\n".join(lines)

    except Exception as e:
        logger.warning("[CROSS-PLATFORM] Failed to build context: %s", e)
        return None


async def build_tier_snapshot(project: Project | None, db: AsyncSession) -> dict:
    """Compact view of the project's compute-tier state for agent context.

    Shape consumed by bash_exec / shell_open / project_control tier_status.
    Returns empty dict when project is None so callers can spread safely.
    """
    if project is None:
        return {}

    try:
        result = await db.execute(select(Container).where(Container.project_id == project.id))
        containers = result.scalars().all()
    except Exception as e:
        logger.warning("[TIER-SNAPSHOT] Failed to load containers: %s", e)
        containers = []

    return {
        "compute_tier": project.compute_tier,
        "active_compute_pod": project.active_compute_pod,
        "environment_status": project.environment_status,
        "last_activity": (
            project.last_activity.isoformat() if project.last_activity is not None else None
        ),
        "namespace": f"proj-{project.id}" if project.compute_tier == "environment" else None,
        "containers": [
            {
                "name": c.name,
                "status": c.status,
                "ready": c.status == "running",
                "is_primary": c.is_primary is True,
                "container_type": c.container_type,
            }
            for c in containers
        ],
    }
