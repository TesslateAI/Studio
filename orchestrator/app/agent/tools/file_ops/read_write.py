"""
File Read/Write Tools

Tools for reading and writing files in user development environments.
Deployment-aware: supports both Docker (shared volume) and Kubernetes (pod API) modes.

Architecture (Docker mode):
- Uses shared tesslate-projects-data volume mounted at /projects
- Each project has files at /projects/{project-slug}/
- Multi-container: /projects/{project-slug}/{container-directory}/
- Direct filesystem access via orchestrator - no temp containers needed

Retry Strategy:
- Automatically retries on transient failures (ConnectionError, TimeoutError, IOError)
- Exponential backoff: 1s → 2s → 4s (up to 3 attempts)
- Non-retryable errors (FileNotFoundError, PermissionError) fail immediately
"""

import logging
from typing import Any

from ..output_formatter import error_output, format_file_size, pluralize, success_output
from ..registry import Tool, ToolCategory
from ..retry_config import tool_retry

logger = logging.getLogger(__name__)


@tool_retry
async def read_file_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Read a file from the user's development environment.

    Uses the unified orchestrator which handles both Docker and Kubernetes modes.
    Filesystem is the source of truth - no database fallback.

    Args:
        params: {file_path: str}
        context: {user_id: UUID, project_id: str, project_slug: str, container_directory: str}

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
    container_name = context.get("container_name")

    logger.info(
        f"[READ-FILE] Reading '{file_path}' - project_slug: {project_slug}, subdir: {container_directory}"
    )

    from ....services.orchestration import get_orchestrator

    try:
        orchestrator = get_orchestrator()
        content = await orchestrator.read_file(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            file_path=file_path,
            project_slug=project_slug,
            subdir=container_directory,
        )

        if content is not None:
            return success_output(
                message=f"Read {format_file_size(len(content))} from '{file_path}'",
                file_path=file_path,
                content=content,
                details={"size_bytes": len(content), "lines": len(content.split("\n"))},
            )

    except Exception as e:
        logger.error(f"[READ-FILE] Failed to read '{file_path}': {e}")

    return error_output(
        message=f"File '{file_path}' does not exist",
        suggestion="Use execute_command with 'ls' or 'find' to browse available files in the directory",
        exists=False,
        file_path=file_path,
    )


@tool_retry
async def write_file_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Write content to a file in the user's development environment.

    Uses the unified orchestrator which handles both Docker and Kubernetes modes.
    Writes directly to filesystem - no database storage.

    Args:
        params: {file_path: str, content: str}
        context: {user_id: UUID, project_id: str, project_slug: str, container_directory: str}

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
    container_name = context.get("container_name")

    # Show a preview of what was written (first and last few lines)
    lines = content.split("\n")
    preview_lines = 5

    if len(lines) <= preview_lines * 2:
        preview = content
    else:
        preview = (
            "\n".join(lines[:preview_lines])
            + "\n\n... ("
            + str(len(lines) - preview_lines * 2)
            + " lines omitted) ...\n\n"
            + "\n".join(lines[-preview_lines:])
        )

    logger.info(
        f"[WRITE-FILE] Writing '{file_path}' - project_slug: {project_slug}, subdir: {container_directory}"
    )

    from ....services.orchestration import get_orchestrator

    try:
        orchestrator = get_orchestrator()
        success = await orchestrator.write_file(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            file_path=file_path,
            content=content,
            project_slug=project_slug,
            subdir=container_directory,
        )

        if success:
            # Auto-sync containers when .tesslate/config.json is written
            if file_path.rstrip("/").endswith(".tesslate/config.json"):
                try:
                    from ....services.base_config_parser import parse_tesslate_config

                    config = parse_tesslate_config(content)
                    if config and config.apps:
                        from ....database import AsyncSessionLocal
                        from ....models import Container

                        async with AsyncSessionLocal() as sync_db:
                            from sqlalchemy import select

                            # Get existing containers
                            existing_result = await sync_db.execute(
                                select(Container).where(
                                    Container.project_id == context["project_id"]
                                )
                            )
                            existing = {c.name: c for c in existing_result.scalars().all()}

                            # Create/update app containers
                            for app_name, app_cfg in config.apps.items():
                                if app_name in existing:
                                    c = existing[app_name]
                                    c.directory = app_cfg.directory
                                    c.internal_port = app_cfg.port or 3000
                                    c.environment_vars = app_cfg.env or {}
                                    del existing[app_name]
                                else:
                                    project_slug = context.get("project_slug", "")
                                    c = Container(
                                        project_id=context["project_id"],
                                        name=app_name,
                                        directory=app_cfg.directory,
                                        container_name=f"{project_slug}-{app_name}",
                                        internal_port=app_cfg.port or 3000,
                                        environment_vars=app_cfg.env or {},
                                        container_type="base",
                                        status="stopped",
                                        position_x=app_cfg.x or 200,
                                        position_y=app_cfg.y or 200,
                                    )
                                    sync_db.add(c)

                            # Delete orphaned containers
                            for orphan in existing.values():
                                if orphan.container_type == "base":
                                    await sync_db.delete(orphan)

                            await sync_db.commit()
                            logger.info(
                                "[AGENT] Auto-synced containers from .tesslate/config.json"
                            )
                except Exception as e:
                    logger.warning(f"[AGENT] Failed to auto-sync containers: {e}")

            return success_output(
                message=f"Wrote {pluralize(len(lines), 'line')} ({format_file_size(len(content))}) to '{file_path}'",
                file_path=file_path,
                preview=preview,
                details={"size_bytes": len(content), "line_count": len(lines)},
            )

    except Exception as e:
        logger.error(f"[WRITE-FILE] Failed to write '{file_path}': {e}")
        return error_output(
            message=f"Could not write to '{file_path}': {str(e)}",
            suggestion="Check if the directory exists and you have write permissions",
            file_path=file_path,
            details={"error": str(e)},
        )

    return error_output(
        message=f"Failed to write to '{file_path}'",
        suggestion="Check if the container has write permissions and sufficient disk space",
        file_path=file_path,
    )


def register_read_write_tools(registry):
    """Register read and write file tools."""

    registry.register(
        Tool(
            name="read_file",
            description="Read the contents of a file from the project directory. Always use this to read actual file content, not get_file_summary.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file relative to project root (e.g., 'src/App.jsx')",
                    }
                },
                "required": ["file_path"],
            },
            executor=read_file_tool,
            category=ToolCategory.FILE_OPS,
            examples=[
                '{"tool_name": "read_file", "parameters": {"file_path": "package.json"}}',
                '{"tool_name": "read_file", "parameters": {"file_path": "src/components/Header.jsx"}}',
            ],
        )
    )

    registry.register(
        Tool(
            name="write_file",
            description="Write complete file content (creates if doesn't exist). Use patch_file or multi_edit for editing existing files to avoid token waste.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file relative to project root",
                    },
                    "content": {
                        "type": "string",
                        "description": "Complete content to write to the file",
                    },
                },
                "required": ["file_path", "content"],
            },
            executor=write_file_tool,
            category=ToolCategory.FILE_OPS,
            examples=[
                '{"tool_name": "write_file", "parameters": {"file_path": "src/NewComponent.jsx", "content": "import React from \'react\'..."}}'
            ],
        )
    )

    logger.info("Registered 2 read/write file tools")
