"""
File Operation Tools

Tools for reading, writing, listing, and deleting files in user development environments.
Deployment-aware: supports both Docker (local filesystem) and Kubernetes (pod API) modes.
"""

import logging
import os
from typing import Dict, Any
from .registry import Tool, ToolRegistry, ToolCategory
from ...config import get_settings

logger = logging.getLogger(__name__)


async def read_file_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Read a file from the user's development environment.

    Deployment-aware:
    - Docker mode: Reads from local filesystem at users/{user_id}/{project_id}/
    - Kubernetes mode: Reads from pod via K8s API

    Args:
        params: {file_path: str}
        context: {user_id: int, project_id: str, db: AsyncSession}

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
        from ...k8s_client import get_k8s_manager
        k8s_manager = get_k8s_manager()
        content = await k8s_manager.read_file_from_pod(
            user_id=user_id,
            project_id=project_id,
            file_path=file_path
        )

        if content is None:
            return {
                "exists": False,
                "message": f"File not found: {file_path}"
            }

        return {
            "exists": True,
            "file_path": file_path,
            "content": content,
            "size": len(content)
        }
    else:
        # Docker mode: Read from local filesystem
        project_dir = f"users/{user_id}/{project_id}"
        full_path = os.path.join(project_dir, file_path)

        if not os.path.exists(full_path):
            return {
                "exists": False,
                "message": f"File not found: {file_path}"
            }

        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()

            return {
                "exists": True,
                "file_path": file_path,
                "content": content,
                "size": len(content)
            }
        except Exception as e:
            return {
                "exists": False,
                "message": f"Error reading file: {str(e)}"
            }


async def write_file_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Write content to a file in the user's development environment.

    Deployment-aware:
    - Docker mode: Writes to local filesystem at users/{user_id}/{project_id}/
    - Kubernetes mode: Writes to pod via K8s API

    Args:
        params: {file_path: str, content: str}
        context: {user_id: int, project_id: str, db: AsyncSession}

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

    if settings.deployment_mode == "kubernetes":
        # Kubernetes mode: Write to pod
        from ...k8s_client import get_k8s_manager
        k8s_manager = get_k8s_manager()
        success = await k8s_manager.write_file_to_pod(
            user_id=user_id,
            project_id=project_id,
            file_path=file_path,
            content=content
        )

        return {
            "success": success,
            "file_path": file_path,
            "size": len(content),
            "message": f"Successfully wrote {len(content)} bytes to {file_path}"
        }
    else:
        # Docker mode: Write to local filesystem
        project_dir = f"users/{user_id}/{project_id}"
        full_path = os.path.join(project_dir, file_path)

        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)

            return {
                "success": True,
                "file_path": file_path,
                "size": len(content),
                "message": f"Successfully wrote {len(content)} bytes to {file_path}"
            }
        except Exception as e:
            return {
                "success": False,
                "file_path": file_path,
                "message": f"Error writing file: {str(e)}"
            }


async def list_files_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    List files in a directory in the user's development environment.

    Deployment-aware:
    - Docker mode: Lists from local filesystem at users/{user_id}/{project_id}/
    - Kubernetes mode: Lists from pod via K8s API

    Args:
        params: {directory: str (default: ".")}
        context: {user_id: int, project_id: str, db: AsyncSession}

    Returns:
        Dict with file listing
    """
    directory = params.get("directory", ".")

    user_id = context["user_id"]
    project_id = str(context["project_id"])
    settings = get_settings()

    if settings.deployment_mode == "kubernetes":
        # Kubernetes mode: List from pod
        from ...k8s_client import get_k8s_manager
        k8s_manager = get_k8s_manager()
        files = await k8s_manager.list_files_in_pod(
            user_id=user_id,
            project_id=project_id,
            directory=directory
        )

        return {
            "directory": directory,
            "files": files,
            "count": len(files)
        }
    else:
        # Docker mode: List from local filesystem
        project_dir = f"users/{user_id}/{project_id}"
        target_dir = os.path.join(project_dir, directory) if directory != "." else project_dir

        if not os.path.exists(target_dir):
            return {
                "directory": directory,
                "files": [],
                "count": 0,
                "message": "Directory not found"
            }

        try:
            files = []
            for item in os.listdir(target_dir):
                item_path = os.path.join(target_dir, item)
                relative_path = os.path.relpath(item_path, project_dir)

                files.append({
                    "name": item,
                    "path": relative_path,
                    "type": "directory" if os.path.isdir(item_path) else "file",
                    "size": os.path.getsize(item_path) if os.path.isfile(item_path) else 0
                })

            return {
                "directory": directory,
                "files": files,
                "count": len(files)
            }
        except Exception as e:
            return {
                "directory": directory,
                "files": [],
                "count": 0,
                "message": f"Error listing directory: {str(e)}"
            }


async def delete_file_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Delete a file from the user's development pod.

    Args:
        params: {file_path: str}
        context: {user_id: int, project_id: str, db: AsyncSession}

    Returns:
        Dict with success status
    """
    file_path = params.get("file_path")
    if not file_path:
        raise ValueError("file_path parameter is required")

    user_id = context["user_id"]
    project_id = str(context["project_id"])

    k8s_manager = get_k8s_manager()
    success = await k8s_manager.delete_file_from_pod(
        user_id=user_id,
        project_id=project_id,
        file_path=file_path
    )

    return {
        "success": success,
        "file_path": file_path,
        "message": f"Successfully deleted {file_path}"
    }


def register_tools(registry: ToolRegistry):
    """Register all file operation tools."""

    registry.register(Tool(
        name="read_file",
        description="Read the contents of a file from the project directory",
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
        description="Write content to a file in the project directory (creates if doesn't exist)",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file relative to project root"
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file"
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

    registry.register(Tool(
        name="list_files",
        description="List files and directories in a given directory",
        parameters={
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Directory path relative to project root (default: '.')",
                    "default": "."
                }
            },
            "required": []
        },
        executor=list_files_tool,
        category=ToolCategory.FILE_OPS,
        examples=[
            '<tool_call><tool_name>list_files</tool_name><parameters>{"directory": "."}</parameters></tool_call>',
            '<tool_call><tool_name>list_files</tool_name><parameters>{"directory": "src"}</parameters></tool_call>'
        ]
    ))

    registry.register(Tool(
        name="delete_file",
        description="Delete a file from the project directory",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to delete"
                }
            },
            "required": ["file_path"]
        },
        executor=delete_file_tool,
        category=ToolCategory.FILE_OPS,
        examples=[
            '<tool_call><tool_name>delete_file</tool_name><parameters>{"file_path": "old_component.jsx"}</parameters></tool_call>'
        ]
    ))

    logger.info("Registered 4 file operation tools")
