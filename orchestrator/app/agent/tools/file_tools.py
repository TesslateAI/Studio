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

    # Show a preview of what was written (first and last few lines)
    lines = content.split('\n')
    preview_lines = 5

    if len(lines) <= preview_lines * 2:
        preview = content
    else:
        preview = '\n'.join(lines[:preview_lines]) + '\n\n... (' + str(len(lines) - preview_lines * 2) + ' lines omitted) ...\n\n' + '\n'.join(lines[-preview_lines:])

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
            "lines": len(lines),
            "preview": preview,
            "message": f"Successfully wrote {len(lines)} lines ({len(content)} bytes) to {file_path}"
        }
    else:
        # Docker mode: Write to local filesystem
        project_dir = f"users/{user_id}/{project_id}"
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

            return {
                "success": True,
                "file_path": file_path,
                "size": len(content),
                "lines": len(lines),
                "preview": preview,
                "message": f"Successfully wrote {len(lines)} lines ({len(content)} bytes) to {file_path}"
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


async def patch_file_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply search/replace edits to an existing file using fuzzy matching.

    This tool allows surgical edits to files without rewriting the entire content.
    Uses progressive fuzzy matching strategies to handle whitespace variations.

    Args:
        params: {
            file_path: str,
            search: str,  # Code block to search for
            replace: str  # Code block to replace it with
        }
        context: {user_id: int, project_id: str, db: AsyncSession}

    Returns:
        Dict with success status and details
    """
    file_path = params.get("file_path")
    search = params.get("search")
    replace = params.get("replace")

    if not file_path:
        raise ValueError("file_path parameter is required")
    if search is None:
        raise ValueError("search parameter is required")
    if replace is None:
        raise ValueError("replace parameter is required")

    user_id = context["user_id"]
    project_id = str(context["project_id"])
    settings = get_settings()

    # Import diff editing utilities
    from ...utils.code_patching import apply_search_replace

    # 1. Read current file content
    current_content = None

    if settings.deployment_mode == "kubernetes":
        from ...k8s_client import get_k8s_manager
        k8s_manager = get_k8s_manager()
        current_content = await k8s_manager.read_file_from_pod(
            user_id=user_id,
            project_id=project_id,
            file_path=file_path
        )
    else:
        # Docker mode: Read from local filesystem
        project_dir = f"users/{user_id}/{project_id}"
        full_path = os.path.join(project_dir, file_path)

        if os.path.exists(full_path):
            with open(full_path, 'r', encoding='utf-8') as f:
                current_content = f.read()

    if current_content is None:
        return {
            "success": False,
            "file_path": file_path,
            "message": f"File not found: {file_path}. Use write_file to create new files."
        }

    # 2. Apply search/replace with fuzzy matching
    result = apply_search_replace(current_content, search, replace, fuzzy=True)

    if not result.success:
        return {
            "success": False,
            "file_path": file_path,
            "message": f"Failed to apply patch: {result.error}",
            "hint": "Make sure the search block matches existing code exactly (including indentation)"
        }

    # 3. Write the patched content back
    if settings.deployment_mode == "kubernetes":
        from ...k8s_client import get_k8s_manager
        k8s_manager = get_k8s_manager()
        success = await k8s_manager.write_file_to_pod(
            user_id=user_id,
            project_id=project_id,
            file_path=file_path,
            content=result.content
        )

        if not success:
            return {
                "success": False,
                "file_path": file_path,
                "message": "Failed to write patched file to pod"
            }
    else:
        # Docker mode: Write to local filesystem
        project_dir = f"users/{user_id}/{project_id}"
        full_path = os.path.join(project_dir, file_path)

        try:
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(result.content)
        except Exception as e:
            return {
                "success": False,
                "file_path": file_path,
                "message": f"Error writing file: {str(e)}"
            }

    return {
        "success": True,
        "file_path": file_path,
        "match_method": result.match_method,
        "message": f"Successfully patched {file_path} using {result.match_method} matching",
        "bytes_written": len(result.content)
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
        name="patch_file",
        description="Apply surgical edits to an existing file using search/replace. More efficient than write_file for small changes. Uses fuzzy matching to handle whitespace variations.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file relative to project root"
                },
                "search": {
                    "type": "string",
                    "description": "Exact code block to find (include 3-5 lines of context for uniqueness, preserve exact indentation)"
                },
                "replace": {
                    "type": "string",
                    "description": "New code block to replace it with"
                }
            },
            "required": ["file_path", "search", "replace"]
        },
        executor=patch_file_tool,
        category=ToolCategory.FILE_OPS,
        examples=[
            '<tool_call><tool_name>patch_file</tool_name><parameters>{"file_path": "src/App.jsx", "search": "  <button className=\\"bg-blue-500\\">\\n    Click Me\\n  </button>", "replace": "  <button className=\\"bg-green-500\\">\\n    Click Me\\n  </button>"}</parameters></tool_call>'
        ]
    ))

    registry.register(Tool(
        name="write_file",
        description="Write complete file content (creates if doesn't exist). Use patch_file for editing existing files to avoid token waste.",
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

    logger.info("Registered 5 file operation tools")
