"""
Project Operation Tools

Tools for getting project information, file trees, and project metadata.
"""

import logging
from typing import Dict, Any
from sqlalchemy import select
from .registry import Tool, ToolRegistry, ToolCategory
from ...models import Project, ProjectFile

logger = logging.getLogger(__name__)


async def get_project_info_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get project metadata and information.

    Args:
        params: {} (uses project_id from context)
        context: {user_id: int, project_id: str, db: AsyncSession}

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
        return {
            "exists": False,
            "error": f"Project {project_id} not found"
        }

    return {
        "exists": True,
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "owner_id": project.owner_id,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None
    }


async def get_file_tree_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get the file tree structure of the project from the database.

    Args:
        params: {} (uses project_id from context)
        context: {user_id: int, project_id: str, db: AsyncSession}

    Returns:
        Dict with file tree
    """
    project_id = context["project_id"]
    db = context["db"]

    result = await db.execute(
        select(ProjectFile).where(ProjectFile.project_id == project_id)
    )
    files = result.scalars().all()

    file_list = [
        {
            "file_path": f.file_path,
            "size": len(f.content) if f.content else 0,
            "created_at": f.created_at.isoformat() if f.created_at else None,
            "updated_at": f.updated_at.isoformat() if f.updated_at else None
        }
        for f in files
    ]

    return {
        "project_id": project_id,
        "total_files": len(file_list),
        "files": file_list
    }


async def get_file_summary_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get a summary of a file's content (first 500 chars) from the database.

    Useful for getting a quick overview without reading the entire file.

    Args:
        params: {file_path: str}
        context: {user_id: int, project_id: str, db: AsyncSession}

    Returns:
        Dict with file summary
    """
    file_path = params.get("file_path")
    if not file_path:
        raise ValueError("file_path parameter is required")

    project_id = context["project_id"]
    db = context["db"]

    result = await db.execute(
        select(ProjectFile).where(
            ProjectFile.project_id == project_id,
            ProjectFile.file_path == file_path
        )
    )
    file = result.scalar_one_or_none()

    if not file:
        return {
            "exists": False,
            "message": f"File not found in database: {file_path}"
        }

    content_preview = file.content[:500] if file.content else ""
    truncated = len(file.content) > 500 if file.content else False

    return {
        "exists": True,
        "file_path": file.file_path,
        "total_size": len(file.content) if file.content else 0,
        "preview": content_preview,
        "truncated": truncated,
        "lines": content_preview.count('\n') + 1 if content_preview else 0
    }


def register_tools(registry: ToolRegistry):
    """Register all project operation tools."""

    registry.register(Tool(
        name="get_project_info",
        description="Get metadata about the current project (name, description, dates, etc.)",
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

    registry.register(Tool(
        name="get_file_tree",
        description="Get the complete file structure of the project from the database",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        },
        executor=get_file_tree_tool,
        category=ToolCategory.PROJECT,
        examples=[
            '<tool_call><tool_name>get_file_tree</tool_name><parameters>{}</parameters></tool_call>'
        ]
    ))

    registry.register(Tool(
        name="get_file_summary",
        description="Get a preview/summary of a file's content (first 500 characters) without reading the whole file",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file"
                }
            },
            "required": ["file_path"]
        },
        executor=get_file_summary_tool,
        category=ToolCategory.PROJECT,
        examples=[
            '<tool_call><tool_name>get_file_summary</tool_name><parameters>{"file_path": "src/App.jsx"}</parameters></tool_call>'
        ]
    ))

    logger.info("Registered 3 project operation tools")
