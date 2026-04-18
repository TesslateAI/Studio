"""
Load Skill Tool

Implements progressive disclosure for the Agent Skills system.
When the agent determines a task matches an available skill's description,
it calls load_skill to get the full instructions.

Skills can come from:
- Database (MarketplaceAgent with item_type='skill')
- Project files (.agents/skills/SKILL.md in container)
"""

import logging
from typing import Any

from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


async def load_skill_executor(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Load a skill's full instructions by name.

    Args:
        params: {
            skill_name: str  # Name of the skill from the available skills catalog
        }
        context: Execution context with available_skills list

    Returns:
        Dict with skill instructions
    """
    skill_name = params.get("skill_name")

    if not skill_name:
        raise ValueError("skill_name parameter is required")

    available_skills = context.get("available_skills", [])

    if not available_skills:
        return error_output(
            message="No skills are available in this session",
            suggestion="Skills must be installed on the agent or present in the project's .agents/skills/ directory",
        )

    # Find matching skill (case-insensitive)
    skill = None
    for s in available_skills:
        if s.name.lower() == skill_name.lower():
            skill = s
            break

    if not skill:
        available_names = [s.name for s in available_skills]
        return error_output(
            message=f"Skill '{skill_name}' not found in available skills",
            suggestion=f"Available skills: {', '.join(available_names)}",
        )

    try:
        if skill.source in ("db", "builtin"):
            body = await _fetch_skill_body_from_db(skill.skill_id, context)
        elif skill.source == "file":
            body = await _read_skill_from_container(skill.file_path, context)
        else:
            return error_output(message=f"Unknown skill source: {skill.source}")

        if not body:
            return error_output(
                message=f"Skill '{skill_name}' has no instructions body",
                suggestion="The skill may be corrupted or incomplete",
            )

        # Built-in skill bodies are marker templates — resolve them against
        # live Python sources (Pydantic models, service catalog, validation
        # constants). Regular DB/file skills pass through unchanged because
        # their bodies contain no markers.
        if skill.source == "builtin":
            from ....services.skill_markers import get_rendered_body

            cache_key = f"skill:{skill.skill_id}" if skill.skill_id else f"skill-name:{skill_name}"
            body = get_rendered_body(cache_key, body)

        result = {
            "message": f"Loaded skill '{skill_name}'",
            "skill_name": skill_name,
            "instructions": body,
        }

        if skill.file_path:
            import os
            result["skill_directory"] = os.path.dirname(skill.file_path)

        return success_output(**result)

    except Exception as e:
        logger.error(f"Failed to load skill '{skill_name}': {e}")
        return error_output(
            message=f"Failed to load skill '{skill_name}': {str(e)}",
            suggestion="Check skill configuration and try again",
        )


async def _fetch_skill_body_from_db(skill_id, context: dict) -> str | None:
    """Fetch skill body from database (lazy load)."""
    db = context.get("db")
    if not db:
        logger.warning("No database session in context for skill loading")
        return None

    from sqlalchemy import select

    from ....models import MarketplaceAgent

    result = await db.execute(
        select(MarketplaceAgent.skill_body).where(
            MarketplaceAgent.id == skill_id,
            MarketplaceAgent.is_active.is_(True),
        )
    )
    row = result.scalar_one_or_none()
    return row


async def _read_skill_from_container(file_path: str, context: dict) -> str | None:
    """Read full SKILL.md from container, strip YAML frontmatter."""
    import asyncio
    import shlex

    from ....services.orchestration import is_kubernetes_mode
    from ....utils.resource_naming import get_container_name

    user_id = context.get("user_id")
    project_id = context.get("project_id")

    if not user_id or not project_id:
        return None

    safe_path = shlex.quote(file_path)

    try:
        if is_kubernetes_mode():
            pod_name = get_container_name(user_id, str(project_id), mode="kubernetes")
            namespace = "tesslate-user-environments"
            cmd = f"kubectl exec -n {namespace} {pod_name} -- cat {safe_path}"
        else:
            container_name = get_container_name(user_id, str(project_id), mode="docker")
            cmd = f"docker exec {container_name} cat {safe_path}"

        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.warning(f"Failed to read skill file {file_path}: {stderr.decode()}")
            return None

        content = stdout.decode("utf-8")

        # Strip YAML frontmatter (between --- markers)
        if content.startswith("---"):
            end_marker = content.find("---", 3)
            if end_marker != -1:
                content = content[end_marker + 3:].strip()

        return content

    except Exception as e:
        logger.error(f"Failed to read skill from container: {e}")
        return None


def register_skill_tools(registry):
    """Register load_skill tool."""

    registry.register(
        Tool(
            name="load_skill",
            description="Load a skill's full instructions by name. Call this when a task matches an available skill's description, or when the user requests a specific skill via slash command. Returns the complete skill instructions and any associated directory path.",
            parameters={
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "Name of the skill from the available skills catalog",
                    },
                },
                "required": ["skill_name"],
            },
            executor=load_skill_executor,
            category=ToolCategory.PROJECT,  # Read-only, safe operation
        )
    )

    logger.info("Registered 1 skill tool")
