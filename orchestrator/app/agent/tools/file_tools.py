"""
File Operation Tools

Tools for reading, writing, listing, and deleting files in user development pods.
Uses the existing Kubernetes client file operations.
"""

import logging
from typing import Dict, Any
from .registry import Tool, ToolRegistry, ToolCategory
from ...k8s_client import get_k8s_manager

logger = logging.getLogger(__name__)


async def read_file_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Read a file from the user's development pod.

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


async def write_file_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Write content to a file in the user's development pod.

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


async def list_files_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    List files in a directory in the user's development pod.

    Args:
        params: {directory: str (default: ".")}
        context: {user_id: int, project_id: str, db: AsyncSession}

    Returns:
        Dict with file listing
    """
    directory = params.get("directory", ".")

    user_id = context["user_id"]
    project_id = str(context["project_id"])

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
