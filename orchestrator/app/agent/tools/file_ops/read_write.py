"""
File Read/Write Tools

Tools for reading and writing files in user development environments.
Deployment-aware: supports both Docker (local filesystem) and Kubernetes (pod API) modes.
"""

import logging
import os
from typing import Dict, Any
from uuid import UUID

from ..registry import Tool, ToolCategory
from ....config import get_settings
from ..output_formatter import success_output, error_output, format_file_size, pluralize
from ....utils.resource_naming import get_project_path

logger = logging.getLogger(__name__)


async def read_file_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Read a file from the user's development environment.

    Deployment-aware:
    - Docker mode: Reads from local filesystem at users/{user_id}/{project_id}/
    - Kubernetes mode: Reads from pod via K8s API

    Args:
        params: {file_path: str}
        context: {user_id: UUID, project_id: str, db: AsyncSession}

    Returns:
        Dict with file content or error
    """
    file_path = params.get("file_path")
    if not file_path:
        raise ValueError("file_path parameter is required")

    user_id = context["user_id"]
    project_id = str(context["project_id"])
    settings = get_settings()

    if settings.deployment_mode == "kubernetes":
        # Kubernetes mode: Read from pod
        from ....k8s_client import get_k8s_manager
        k8s_manager = get_k8s_manager()
        content = await k8s_manager.read_file_from_pod(
            user_id=user_id,
            project_id=project_id,
            file_path=file_path
        )

        if content is None:
            return error_output(
                message=f"File '{file_path}' does not exist",
                suggestion="Use list_files to browse available files in the directory",
                exists=False,
                file_path=file_path
            )

        return success_output(
            message=f"Read {format_file_size(len(content))} from '{file_path}'",
            file_path=file_path,
            content=content,
            details={
                "size_bytes": len(content),
                "lines": len(content.split('\n'))
            }
        )
    else:
        # Docker mode: Read from local filesystem
        project_dir = get_project_path(user_id, project_id)
        full_path = os.path.join(project_dir, file_path)

        if not os.path.exists(full_path):
            return error_output(
                message=f"File '{file_path}' does not exist",
                suggestion="Use list_files to browse available files in the directory",
                exists=False,
                file_path=file_path
            )

        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()

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
            return error_output(
                message=f"Could not read '{file_path}': {str(e)}",
                suggestion="Check if the file has read permissions or is a binary file",
                file_path=file_path,
                details={"error": str(e)}
            )


async def write_file_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Write content to a file in the user's development environment.

    Deployment-aware:
    - Docker mode: Writes to local filesystem at users/{user_id}/{project_id}/
    - Kubernetes mode: Writes to pod via K8s API

    Args:
        params: {file_path: str, content: str}
        context: {user_id: UUID, project_id: str, db: AsyncSession}

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
    settings = get_settings()

    # Show a preview of what was written (first and last few lines)
    lines = content.split('\n')
    preview_lines = 5

    if len(lines) <= preview_lines * 2:
        preview = content
    else:
        preview = '\n'.join(lines[:preview_lines]) + '\n\n... (' + str(len(lines) - preview_lines * 2) + ' lines omitted) ...\n\n' + '\n'.join(lines[-preview_lines:])

    if settings.deployment_mode == "kubernetes":
        # Kubernetes mode: Write to pod
        from ....k8s_client import get_k8s_manager
        k8s_manager = get_k8s_manager()
        success = await k8s_manager.write_file_to_pod(
            user_id=user_id,
            project_id=project_id,
            file_path=file_path,
            content=content
        )

        if not success:
            return error_output(
                message=f"Failed to write to '{file_path}' in pod",
                suggestion="Check if the pod has write permissions and sufficient disk space",
                file_path=file_path
            )

        return success_output(
            message=f"Wrote {pluralize(len(lines), 'line')} ({format_file_size(len(content))}) to '{file_path}'",
            file_path=file_path,
            preview=preview,
            details={
                "size_bytes": len(content),
                "line_count": len(lines)
            }
        )
    else:
        # Docker mode: Write to local filesystem
        project_dir = get_project_path(user_id, project_id)
        full_path = os.path.join(project_dir, file_path)

        try:
            # Create parent directory (with safety check for Windows Docker volumes)
            parent_dir = os.path.dirname(full_path)
            if parent_dir:
                try:
                    os.makedirs(parent_dir, exist_ok=True)
                except FileExistsError:
                    # Handle race condition on Windows Docker volumes - verify it exists
                    if not os.path.exists(parent_dir):
                        raise

            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)

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
            return error_output(
                message=f"Could not write to '{file_path}': {str(e)}",
                suggestion="Check if the directory exists and you have write permissions",
                file_path=file_path,
                details={"error": str(e)}
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
            '<tool_call><tool_name>read_file</tool_name><parameters>{"file_path": "package.json"}</parameters></tool_call>',
            '<tool_call><tool_name>read_file</tool_name><parameters>{"file_path": "src/components/Header.jsx"}</parameters></tool_call>'
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
            '<tool_call><tool_name>write_file</tool_name><parameters>{"file_path": "src/NewComponent.jsx", "content": "import React from \'react\'..."}</parameters></tool_call>'
        ]
    ))

    logger.info("Registered 2 read/write file tools")
