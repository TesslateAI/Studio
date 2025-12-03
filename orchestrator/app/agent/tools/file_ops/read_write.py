"""
File Read/Write Tools

Tools for reading and writing files in user development environments.
Deployment-aware: supports both Docker (shared volume) and Kubernetes (pod API) modes.

Architecture (Docker mode):
- Uses shared tesslate-projects-data volume mounted at /projects
- Each project has files at /projects/{project-slug}/
- Direct filesystem access - no temp containers needed

Retry Strategy:
- Automatically retries on transient failures (ConnectionError, TimeoutError, IOError)
- Exponential backoff: 1s → 2s → 4s (up to 3 attempts)
- Non-retryable errors (FileNotFoundError, PermissionError) fail immediately
"""

import logging
import os
from typing import Dict, Any
from uuid import UUID

from ..registry import Tool, ToolCategory
from ....config import get_settings
from ..output_formatter import success_output, error_output, format_file_size, pluralize
from ..retry_config import tool_retry

logger = logging.getLogger(__name__)


@tool_retry
async def read_file_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Read a file from the user's development environment.

    Deployment-aware:
    - Docker mode: Reads from shared volume at /projects/{project-slug}/
    - Kubernetes mode: Reads from pod via K8s API

    Retry behavior:
    - Automatically retries on ConnectionError, TimeoutError, IOError
    - Up to 3 attempts with exponential backoff (1s, 2s, 4s)
    - FileNotFoundError and PermissionError fail immediately

    Args:
        params: {file_path: str}
        context: {user_id: UUID, project_id: str, project_slug: str, db: AsyncSession}

    Returns:
        Dict with file content or error
    """
    file_path = params.get("file_path")
    if not file_path:
        raise ValueError("file_path parameter is required")

    user_id = context["user_id"]
    project_id = str(context["project_id"])
    project_slug = context.get("project_slug")
    container_directory = context.get("container_directory")  # Container subdir for scoped agents
    db = context.get("db")

    # Debug logging for container scoping
    logger.info(f"[READ-FILE] Reading '{file_path}' - project_slug: {project_slug}, container_directory: {container_directory}")

    # Get container name for multi-container projects
    container_name = context.get("container_name")

    from ....services.orchestration import get_orchestrator, is_kubernetes_mode

    # Try unified orchestrator first
    try:
        orchestrator = get_orchestrator()
        content = await orchestrator.read_file(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            file_path=file_path
        )

        if content is not None:
            return success_output(
                message=f"Read {format_file_size(len(content))} from '{file_path}'",
                file_path=file_path,
                content=content,
                details={
                    "size_bytes": len(content),
                    "lines": len(content.split('\n'))
                }
            )
    except Exception as e:
        logger.debug(f"Could not read via orchestrator: {e}")

    # Fallback: Docker mode - Try shared volume (direct filesystem access)
    if not is_kubernetes_mode() and project_slug:
        try:
            from ....services.volume_manager import get_volume_manager
            volume_manager = get_volume_manager()

            # If container_directory is set, files are relative to that subdir
            content = await volume_manager.read_file(project_slug, file_path, subdir=container_directory)

            if content is not None:
                return success_output(
                    message=f"Read {format_file_size(len(content))} from '{file_path}'",
                    file_path=file_path,
                    content=content,
                    details={
                        "size_bytes": len(content),
                        "lines": len(content.split('\n')),
                        "source": "shared_volume"
                    }
                )
        except Exception as e:
            logger.debug(f"Could not read from shared volume: {e}")

    # Strategy 2: Try database as fallback
    if db:
        try:
            from ....models import Project, ProjectFile
            from sqlalchemy import select

            # Get project slug if not provided
            if not project_slug:
                project_result = await db.execute(
                    select(Project).where(Project.id == UUID(project_id))
                )
                project = project_result.scalar_one_or_none()
                if project:
                    project_slug = project.slug

                    # Try shared volume with the retrieved slug
                    try:
                        from ....services.volume_manager import get_volume_manager
                        volume_manager = get_volume_manager()

                        content = await volume_manager.read_file(project_slug, file_path, subdir=container_directory)

                        if content is not None:
                            return success_output(
                                message=f"Read {format_file_size(len(content))} from '{file_path}'",
                                file_path=file_path,
                                content=content,
                                details={
                                    "size_bytes": len(content),
                                    "lines": len(content.split('\n')),
                                    "source": "shared_volume"
                                }
                            )
                    except Exception as e:
                        logger.debug(f"Could not read from shared volume: {e}")

            # Try database as final fallback
            result = await db.execute(
                select(ProjectFile).where(
                    ProjectFile.project_id == UUID(project_id),
                    ProjectFile.file_path == file_path
                )
            )
            db_file = result.scalar_one_or_none()

            if db_file and db_file.content:
                return success_output(
                    message=f"Read {format_file_size(len(db_file.content))} from '{file_path}' (database)",
                    file_path=file_path,
                    content=db_file.content,
                    details={
                        "size_bytes": len(db_file.content),
                        "lines": len(db_file.content.split('\n')),
                        "source": "database"
                    }
                )
        except Exception as e:
            logger.debug(f"Could not read from database: {e}")

    return error_output(
        message=f"File '{file_path}' does not exist",
        suggestion="Use execute_command with 'ls' or 'find' to browse available files in the directory",
        exists=False,
        file_path=file_path
    )


@tool_retry
async def write_file_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Write content to a file in the user's development environment.

    Deployment-aware:
    - Docker mode: Writes to shared volume at /projects/{project-slug}/
    - Kubernetes mode: Writes to pod via K8s API

    Retry behavior:
    - Automatically retries on ConnectionError, TimeoutError, IOError
    - Up to 3 attempts with exponential backoff (1s, 2s, 4s)
    - PermissionError fails immediately

    Args:
        params: {file_path: str, content: str}
        context: {user_id: UUID, project_id: str, project_slug: str, db: AsyncSession}

    Returns:
        Dict with success status
    """
    file_path = params.get("file_path")
    content = params.get("content")

    if not file_path:
        raise ValueError("file_path parameter is required")
    if content is None:
        raise ValueError("content parameter is required")

    user_id = context["user_id"]
    project_id = str(context["project_id"])
    project_slug = context.get("project_slug")
    container_directory = context.get("container_directory")  # Container subdir for scoped agents
    db = context.get("db")

    # Show a preview of what was written (first and last few lines)
    lines = content.split('\n')
    preview_lines = 5

    if len(lines) <= preview_lines * 2:
        preview = content
    else:
        preview = '\n'.join(lines[:preview_lines]) + '\n\n... (' + str(len(lines) - preview_lines * 2) + ' lines omitted) ...\n\n' + '\n'.join(lines[-preview_lines:])

    # Get container info for multi-container projects
    container_name = context.get("container_name")

    from ....services.orchestration import get_orchestrator, is_kubernetes_mode

    # Try unified orchestrator first
    try:
        orchestrator = get_orchestrator()
        success = await orchestrator.write_file(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            file_path=file_path,
            content=content
        )

        if success:
            return success_output(
                message=f"Wrote {pluralize(len(lines), 'line')} ({format_file_size(len(content))}) to '{file_path}'",
                file_path=file_path,
                preview=preview,
                details={
                    "size_bytes": len(content),
                    "line_count": len(lines)
                }
            )
    except Exception as e:
        logger.debug(f"Could not write via orchestrator: {e}")

    # Fallback: Docker mode - write to shared volume and database
    if not is_kubernetes_mode():
        # Docker mode: Write to shared volume and database
        try:
            # Get project slug if not provided
            if not project_slug and db:
                try:
                    from ....models import Project
                    from sqlalchemy import select

                    project_result = await db.execute(
                        select(Project).where(Project.id == UUID(project_id))
                    )
                    project = project_result.scalar_one_or_none()
                    if project:
                        project_slug = project.slug
                except Exception as e:
                    logger.warning(f"[AGENT] Could not get project slug: {e}")

            # Step 1: Write to shared volume (primary storage)
            volume_write_success = False
            if project_slug:
                try:
                    from ....services.volume_manager import get_volume_manager
                    volume_manager = get_volume_manager()

                    volume_write_success = await volume_manager.write_file(
                        project_slug,
                        file_path,
                        content,
                        subdir=container_directory
                    )

                    if volume_write_success:
                        subdir_log = f"/{container_directory}" if container_directory else ""
                        logger.info(f"[AGENT] Wrote {file_path} to shared volume /projects/{project_slug}{subdir_log}")
                except Exception as e:
                    logger.warning(f"[AGENT] Failed to write to shared volume: {e}")

            # Step 2: Write to database (backup/version history)
            if db:
                try:
                    from ....models import ProjectFile
                    from sqlalchemy import select

                    result = await db.execute(
                        select(ProjectFile).where(
                            ProjectFile.project_id == UUID(project_id),
                            ProjectFile.file_path == file_path
                        )
                    )
                    existing_file = result.scalar_one_or_none()

                    if existing_file:
                        existing_file.content = content
                    else:
                        new_file = ProjectFile(
                            project_id=UUID(project_id),
                            file_path=file_path,
                            content=content
                        )
                        db.add(new_file)

                    await db.commit()
                    logger.info(f"[AGENT] Saved {file_path} to database")
                except Exception as e:
                    logger.warning(f"[AGENT] Failed to save to database: {e}")

            return success_output(
                message=f"Wrote {pluralize(len(lines), 'line')} ({format_file_size(len(content))}) to '{file_path}'",
                file_path=file_path,
                preview=preview,
                details={
                    "size_bytes": len(content),
                    "line_count": len(lines),
                    "storage": "shared_volume" if volume_write_success else "database_only"
                }
            )
        except Exception as e:
            return error_output(
                message=f"Could not write to '{file_path}': {str(e)}",
                suggestion="Check if the directory exists and you have write permissions",
                file_path=file_path,
                details={"error": str(e)}
            )

    # If we get here, orchestrator failed and we're not in Docker mode
    return error_output(
        message=f"Failed to write to '{file_path}'",
        suggestion="Check if the container has write permissions and sufficient disk space",
        file_path=file_path
    )


def register_read_write_tools(registry):
    """Register read and write file tools."""

    registry.register(Tool(
        name="read_file",
        description="Read the contents of a file from the project directory. Always use this to read actual file content, not get_file_summary.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file relative to project root (e.g., 'src/App.jsx')"
                }
            },
            "required": ["file_path"]
        },
        executor=read_file_tool,
        category=ToolCategory.FILE_OPS,
        examples=[
            '{"tool_name": "read_file", "parameters": {"file_path": "package.json"}}',
            '{"tool_name": "read_file", "parameters": {"file_path": "src/components/Header.jsx"}}'
        ]
    ))

    registry.register(Tool(
        name="write_file",
        description="Write complete file content (creates if doesn't exist). Use patch_file or multi_edit for editing existing files to avoid token waste.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file relative to project root"
                },
                "content": {
                    "type": "string",
                    "description": "Complete content to write to the file"
                }
            },
            "required": ["file_path", "content"]
        },
        executor=write_file_tool,
        category=ToolCategory.FILE_OPS,
        examples=[
            '{"tool_name": "write_file", "parameters": {"file_path": "src/NewComponent.jsx", "content": "import React from \'react\'..."}}'
        ]
    ))

    logger.info("Registered 2 read/write file tools")
