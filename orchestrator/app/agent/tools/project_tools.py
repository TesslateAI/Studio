"""
Project Operation Tools

Tools for getting project information, file trees, and project metadata.
"""

import logging
from typing import Dict, Any
from sqlalchemy import select
from .registry import Tool, ToolRegistry, ToolCategory
from ...models import Project, ProjectFile
from .output_formatter import success_output, error_output, format_file_size, pluralize

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

    return success_output(
        message=f"Found {pluralize(len(file_list), 'file')} in project",
        project_id=project_id,
        files=file_list,
        details={"total_files": len(file_list)}
    )


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
        return error_output(
            message=f"File '{file_path}' not found in database",
            suggestion="Use get_file_tree to see available files, or read_file to read from filesystem",
            exists=False,
            file_path=file_path
        )

    content_preview = file.content[:500] if file.content else ""
    truncated = len(file.content) > 500 if file.content else False
    total_size = len(file.content) if file.content else 0

    if truncated:
        message = f"Preview of '{file_path}' ({format_file_size(total_size)}, truncated)"
    else:
        message = f"Preview of '{file_path}' ({format_file_size(total_size)})"

    return success_output(
        message=message,
        file_path=file.file_path,
        preview=content_preview,
        details={
            "total_size_bytes": total_size,
            "truncated": truncated,
            "preview_lines": content_preview.count('\n') + 1 if content_preview else 0
        }
    )


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
        description="DEPRECATED: Use read_file instead. This tool only shows first 500 chars from database cache (often stale). For actual file content, always use read_file.",
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
