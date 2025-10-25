"""
File Edit Tools

Tools for making surgical edits to existing files.
Supports single edits (patch_file) and batch edits (multi_edit).
"""

import logging
import os
from typing import Dict, Any, List
from uuid import UUID

from ..registry import Tool, ToolCategory
from ....config import get_settings
from ..output_formatter import success_output, error_output
from ....utils.resource_naming import get_project_path

logger = logging.getLogger(__name__)


async def patch_file_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply search/replace edit to an existing file using fuzzy matching.

    This tool allows surgical edits to files without rewriting the entire content.
    Uses progressive fuzzy matching strategies to handle whitespace variations.

    Args:
        params: {
            file_path: str,
            search: str,  # Code block to search for
            replace: str  # Code block to replace it with
        }
        context: {user_id: UUID, project_id: str, db: AsyncSession}

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
    from ....utils.code_patching import apply_search_replace

    # 1. Read current file content
    current_content = None

    if settings.deployment_mode == "kubernetes":
        from ....k8s_client import get_k8s_manager
        k8s_manager = get_k8s_manager()
        current_content = await k8s_manager.read_file_from_pod(
            user_id=user_id,
            project_id=project_id,
            file_path=file_path
        )
    else:
        # Docker mode: Read from local filesystem
        project_dir = get_project_path(user_id, project_id)
        full_path = os.path.join(project_dir, file_path)

        if os.path.exists(full_path):
            with open(full_path, 'r', encoding='utf-8') as f:
                current_content = f.read()

    if current_content is None:
        return error_output(
            message=f"File '{file_path}' does not exist",
            suggestion="Use write_file to create new files, or list_files to check available files",
            file_path=file_path
        )

    # 2. Apply search/replace with fuzzy matching
    result = apply_search_replace(current_content, search, replace, fuzzy=True)

    if not result.success:
        return error_output(
            message=f"Could not find matching code in '{file_path}'",
            suggestion="Make sure the search block matches existing code exactly (including indentation and whitespace)",
            file_path=file_path,
            details={"error": result.error}
        )

    # 3. Write the patched content back
    if settings.deployment_mode == "kubernetes":
        from ....k8s_client import get_k8s_manager
        k8s_manager = get_k8s_manager()
        success = await k8s_manager.write_file_to_pod(
            user_id=user_id,
            project_id=project_id,
            file_path=file_path,
            content=result.content
        )

        if not success:
            return error_output(
                message=f"Failed to save patched file '{file_path}' to pod",
                suggestion="Check pod write permissions and disk space",
                file_path=file_path
            )
    else:
        # Docker mode: Write to local filesystem
        project_dir = get_project_path(user_id, project_id)
        full_path = os.path.join(project_dir, file_path)

        try:
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(result.content)
        except Exception as e:
            return error_output(
                message=f"Could not save patched file '{file_path}': {str(e)}",
                suggestion="Check if you have write permissions",
                file_path=file_path,
                details={"error": str(e)}
            )

    # Generate a diff preview showing what changed
    def generate_diff_preview(old: str, new: str, max_lines: int = 10) -> str:
        """Generate a concise diff preview showing changes."""
        import difflib

        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)

        diff = list(difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile='before',
            tofile='after',
            lineterm='',
            n=2  # Context lines
        ))

        if not diff:
            return "No changes"

        # Skip the header lines (--- and +++)
        diff_body = [line.rstrip() for line in diff[2:]]

        # Truncate if too long
        if len(diff_body) > max_lines:
            diff_body = diff_body[:max_lines] + [f"... ({len(diff_body) - max_lines} more lines)"]

        return '\n'.join(diff_body)

    diff_preview = generate_diff_preview(current_content, result.content)

    return success_output(
        message=f"Successfully patched '{file_path}'",
        file_path=file_path,
        diff=diff_preview,
        details={
            "match_method": result.match_method,
            "size_bytes": len(result.content)
        }
    )


async def multi_edit_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply multiple search/replace edits to a single file atomically.

    More efficient than multiple patch_file calls. All edits succeed or all fail.

    Args:
        params: {
            file_path: str,
            edits: [
                {search: str, replace: str},
                ...
            ]
        }
        context: {user_id: UUID, project_id: str, db: AsyncSession}

    Returns:
        Dict with success status and details
    """
    file_path = params.get("file_path")
    edits = params.get("edits", [])

    if not file_path:
        raise ValueError("file_path parameter is required")
    if not edits:
        raise ValueError("edits parameter is required and must be non-empty")
    if not isinstance(edits, list):
        raise ValueError("edits must be a list of {search, replace} objects")

    user_id = context["user_id"]
    project_id = str(context["project_id"])
    settings = get_settings()

    # Import diff editing utilities
    from ....utils.code_patching import apply_search_replace

    # 1. Read current file content
    current_content = None

    if settings.deployment_mode == "kubernetes":
        from ....k8s_client import get_k8s_manager
        k8s_manager = get_k8s_manager()
        current_content = await k8s_manager.read_file_from_pod(
            user_id=user_id,
            project_id=project_id,
            file_path=file_path
        )
    else:
        # Docker mode: Read from local filesystem
        project_dir = get_project_path(user_id, project_id)
        full_path = os.path.join(project_dir, file_path)

        if os.path.exists(full_path):
            with open(full_path, 'r', encoding='utf-8') as f:
                current_content = f.read()

    if current_content is None:
        return error_output(
            message=f"File '{file_path}' does not exist",
            suggestion="Use write_file to create new files, or list_files to check available files",
            file_path=file_path
        )

    # 2. Apply edits sequentially (each operates on result of previous)
    content = current_content
    applied_edits = []

    for i, edit in enumerate(edits):
        search = edit.get("search")
        replace = edit.get("replace")

        if search is None or replace is None:
            return error_output(
                message=f"Edit {i+1} is missing 'search' or 'replace' field",
                suggestion="Each edit must have both 'search' and 'replace' fields",
                file_path=file_path,
                details={"edit_index": i}
            )

        result = apply_search_replace(content, search, replace, fuzzy=True)

        if not result.success:
            return error_output(
                message=f"Edit {i+1}/{len(edits)} failed: could not find matching code in '{file_path}'",
                suggestion="Make sure all search blocks match existing code exactly (including indentation)",
                file_path=file_path,
                details={
                    "edit_index": i,
                    "error": result.error,
                    "applied_edits": applied_edits
                }
            )

        content = result.content
        applied_edits.append({
            "index": i,
            "match_method": result.match_method
        })

    # 3. Write the patched content back
    if settings.deployment_mode == "kubernetes":
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
                message=f"Failed to save edited file '{file_path}' to pod",
                suggestion="Check pod write permissions and disk space",
                file_path=file_path
            )
    else:
        # Docker mode: Write to local filesystem
        project_dir = get_project_path(user_id, project_id)
        full_path = os.path.join(project_dir, file_path)

        try:
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            return error_output(
                message=f"Could not save edited file '{file_path}': {str(e)}",
                suggestion="Check if you have write permissions",
                file_path=file_path,
                details={"error": str(e)}
            )

    # Generate a diff preview showing what changed
    def generate_diff_preview(old: str, new: str, max_lines: int = 10) -> str:
        """Generate a concise diff preview showing changes."""
        import difflib

        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)

        diff = list(difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile='before',
            tofile='after',
            lineterm='',
            n=2  # Context lines
        ))

        if not diff:
            return "No changes"

        # Skip the header lines (--- and +++)
        diff_body = [line.rstrip() for line in diff[2:]]

        # Truncate if too long
        if len(diff_body) > max_lines:
            diff_body = diff_body[:max_lines] + [f"... ({len(diff_body) - max_lines} more lines)"]

        return '\n'.join(diff_body)

    diff_preview = generate_diff_preview(current_content, content)

    return success_output(
        message=f"Successfully applied {len(edits)} edits to '{file_path}'",
        file_path=file_path,
        diff=diff_preview,
        details={
            "edit_count": len(edits),
            "applied_edits": applied_edits,
            "size_bytes": len(content)
        }
    )


def register_edit_tools(registry):
    """Register file edit tools."""

    registry.register(Tool(
        name="patch_file",
        description="Apply surgical edit to an existing file using search/replace. More efficient than write_file for small changes. Uses fuzzy matching to handle whitespace variations.",
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
        name="multi_edit",
        description="Apply multiple search/replace edits to a single file atomically. More efficient than multiple patch_file calls. All edits are applied sequentially (each operates on the result of the previous edit).",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file relative to project root"
                },
                "edits": {
                    "type": "array",
                    "description": "List of search/replace operations to apply in sequence",
                    "items": {
                        "type": "object",
                        "properties": {
                            "search": {
                                "type": "string",
                                "description": "Code block to find"
                            },
                            "replace": {
                                "type": "string",
                                "description": "Code block to replace it with"
                            }
                        },
                        "required": ["search", "replace"]
                    }
                }
            },
            "required": ["file_path", "edits"]
        },
        executor=multi_edit_tool,
        category=ToolCategory.FILE_OPS,
        examples=[
            '<tool_call><tool_name>multi_edit</tool_name><parameters>{"file_path": "src/App.jsx", "edits": [{"search": "const [count, setCount] = useState(0)", "replace": "const [count, setCount] = useState(10)"}, {"search": "bg-blue-500", "replace": "bg-green-500"}]}</parameters></tool_call>'
        ]
    ))

    logger.info("Registered 2 file edit tools")
