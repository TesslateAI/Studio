"""
Project Metadata Tools

Tools for getting project information from the database.
Use bash_exec for file listings instead of stale DB cache.
"""

import logging
from typing import Dict, Any
from uuid import UUID
from sqlalchemy import select

from ..registry import Tool, ToolCategory
from ....models import Project
from ..output_formatter import success_output, error_output

logger = logging.getLogger(__name__)


async def get_project_info_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get project metadata and information.

    Args:
        params: {} (uses project_id from context)
        context: {user_id: UUID, project_id: str, db: AsyncSession}

    Returns:
        Dict with project information
    """
    project_id = context["project_id"]
    db = context["db"]

    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()

    if not project:
        return error_output(
            message=f"Project {project_id} not found",
            suggestion="Check if the project exists or you have access to it",
            exists=False
        )

    return success_output(
        message=f"Project: {project.name}",
        id=project.id,
        name=project.name,
        description=project.description,
        details={
            "owner_id": project.owner_id,
            "created_at": project.created_at.isoformat() if project.created_at else None,
            "updated_at": project.updated_at.isoformat() if project.updated_at else None
        }
    )


def register_project_tools(registry):
    """Register project operation tools."""

    registry.register(Tool(
        name="get_project_info",
        description="Get metadata about the current project (name, description, dates, owner, etc.). Use bash_exec with 'find' or 'ls -R' for file listings.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        },
        executor=get_project_info_tool,
        category=ToolCategory.PROJECT,
        examples=[
            '<tool_call><tool_name>get_project_info</tool_name><parameters>{}</parameters></tool_call>'
        ]
    ))

    logger.info("Registered 1 project operation tool")
