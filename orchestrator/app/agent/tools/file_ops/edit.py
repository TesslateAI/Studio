"""
File Edit Tools

Tools for making surgical edits to existing files.
Supports single edits (patch_file) and batch edits (multi_edit).
Deployment-aware: supports both Docker (shared volume) and Kubernetes (pod API) modes.

Retry Strategy:
- Automatically retries on transient failures (ConnectionError, TimeoutError, IOError)
- Exponential backoff: 1s → 2s → 4s (up to 3 attempts)
"""

import logging
from typing import Dict, Any, List

from ..registry import Tool, ToolCategory
from ..output_formatter import success_output, error_output
from ..retry_config import tool_retry

logger = logging.getLogger(__name__)


@tool_retry
async def patch_file_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply search/replace edit to an existing file using fuzzy matching.

    Uses the unified orchestrator which handles both Docker and Kubernetes modes.
    Filesystem is the source of truth - no database fallback.

    Args:
        params: {file_path: str, search: str, replace: str}
        context: {user_id: UUID, project_id: str, project_slug: str, container_directory: str}

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
    project_slug = context.get("project_slug")
    container_directory = context.get("container_directory")  # Container subdir for scoped agents
    container_name = context.get("container_name")

    logger.info(f"[PATCH-FILE] Patching '{file_path}' - project_slug: {project_slug}, subdir: {container_directory}")

    from ....utils.code_patching import apply_search_replace
    from ....services.orchestration import get_orchestrator

    # 1. Read current file content
    try:
        orchestrator = get_orchestrator()
        current_content = await orchestrator.read_file(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            file_path=file_path,
            project_slug=project_slug,
            subdir=container_directory
        )
    except Exception as e:
        logger.error(f"[PATCH-FILE] Failed to read '{file_path}': {e}")
        current_content = None

    if current_content is None:
        return error_output(
            message=f"File '{file_path}' does not exist",
            suggestion="Use write_file to create new files, or execute_command with 'ls' to check available files",
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
    try:
        success = await orchestrator.write_file(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            file_path=file_path,
            content=result.content,
            project_slug=project_slug,
            subdir=container_directory
        )

        if not success:
            return error_output(
                message=f"Failed to save patched file '{file_path}'",
                suggestion="Check container write permissions and disk space",
                file_path=file_path
            )
    except Exception as e:
        logger.error(f"[PATCH-FILE] Failed to write '{file_path}': {e}")
        return error_output(
            message=f"Could not save patched file '{file_path}': {str(e)}",
            suggestion="Check if you have write permissions",
            file_path=file_path,
            details={"error": str(e)}
        )

    # Generate a diff preview showing what changed
    diff_preview = _generate_diff_preview(current_content, result.content)

    return success_output(
        message=f"Successfully patched '{file_path}'",
        file_path=file_path,
        diff=diff_preview,
        details={
            "match_method": result.match_method,
            "size_bytes": len(result.content)
        }
    )


def _generate_diff_preview(old: str, new: str, max_lines: int = 10) -> str:
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


@tool_retry
async def multi_edit_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply multiple search/replace edits to a single file atomically.

    Uses the unified orchestrator which handles both Docker and Kubernetes modes.
    Filesystem is the source of truth - no database fallback.

    Args:
        params: {file_path: str, edits: [{search: str, replace: str}, ...]}
        context: {user_id: UUID, project_id: str, project_slug: str, container_directory: str}

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
    project_slug = context.get("project_slug")
    container_directory = context.get("container_directory")  # Container subdir for scoped agents
    container_name = context.get("container_name")

    logger.info(f"[MULTI-EDIT] Editing '{file_path}' with {len(edits)} edits - project_slug: {project_slug}, subdir: {container_directory}")

    from ....utils.code_patching import apply_search_replace
    from ....services.orchestration import get_orchestrator

    # 1. Read current file content
    try:
        orchestrator = get_orchestrator()
        current_content = await orchestrator.read_file(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            file_path=file_path,
            project_slug=project_slug,
            subdir=container_directory
        )
    except Exception as e:
        logger.error(f"[MULTI-EDIT] Failed to read '{file_path}': {e}")
        current_content = None

    if current_content is None:
        return error_output(
            message=f"File '{file_path}' does not exist",
            suggestion="Use write_file to create new files, or execute_command with 'ls' to check available files",
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
    try:
        success = await orchestrator.write_file(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            file_path=file_path,
            content=content,
            project_slug=project_slug,
            subdir=container_directory
        )

        if not success:
            return error_output(
                message=f"Failed to save edited file '{file_path}'",
                suggestion="Check container write permissions and disk space",
                file_path=file_path
            )
    except Exception as e:
        logger.error(f"[MULTI-EDIT] Failed to write '{file_path}': {e}")
        return error_output(
            message=f"Could not save edited file '{file_path}': {str(e)}",
            suggestion="Check if you have write permissions",
            file_path=file_path,
            details={"error": str(e)}
        )

    diff_preview = _generate_diff_preview(current_content, content)

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
            '{"tool_name": "patch_file", "parameters": {"file_path": "src/App.jsx", "search": "  <button className=\\"bg-blue-500\\">\\n    Click Me\\n  </button>", "replace": "  <button className=\\"bg-green-500\\">\\n    Click Me\\n  </button>"}}'
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
            '{"tool_name": "multi_edit", "parameters": {"file_path": "src/App.jsx", "edits": [{"search": "const [count, setCount] = useState(0)", "replace": "const [count, setCount] = useState(10)"}, {"search": "bg-blue-500", "replace": "bg-green-500"}]}}'
        ]
    ))

    logger.info("Registered 2 file edit tools")
