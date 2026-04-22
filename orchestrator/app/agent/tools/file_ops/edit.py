"""
File Edit Tools

Tools for making surgical edits to existing files.

Exposes two wire-compatible tools:
    * ``patch_file`` -- single search/replace with fuzzy matching
    * ``multi_edit`` -- batch of sequential search/replace operations

Both tools delegate their actual matching to :mod:`fuzzy_editor`, which
runs a three-strategy pipeline (exact -> flexible whitespace ->
Levenshtein fuzzy) with an optional LLM-repair pass when every strategy
misses. Every successful mutation is recorded in :data:`EDIT_HISTORY`
so the ``file_undo`` tool can revert it.
"""

from __future__ import annotations

import difflib
import logging
from typing import Any

from ....services.orchestration import get_orchestrator
from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory
from ..retry_config import tool_retry
from .edit_history import EDIT_HISTORY
from .fuzzy_editor import EditError, EditResult, apply_edit, llm_repair

logger = logging.getLogger(__name__)


def _resolve_strings(params: dict[str, Any]) -> tuple[str | None, str | None]:
    """Accept either ``old_str`` / ``new_str`` or legacy ``search`` / ``replace``."""
    old = params.get("old_str")
    new = params.get("new_str")
    if old is None:
        old = params.get("search")
    if new is None:
        new = params.get("replace")
    return old, new


def _generate_diff_preview(old: str, new: str, max_lines: int = 10) -> str:
    """Generate a concise diff preview showing changes."""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)

    diff = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="before",
            tofile="after",
            lineterm="",
            n=2,
        )
    )
    if not diff:
        return "No changes"
    diff_body = [line.rstrip() for line in diff[2:]]
    if len(diff_body) > max_lines:
        diff_body = diff_body[:max_lines] + [f"... ({len(diff_body) - max_lines} more lines)"]
    return "\n".join(diff_body)


def _int_param(params: dict[str, Any], key: str, default: int) -> int:
    value = params.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bool_param(params: dict[str, Any], key: str, default: bool) -> bool:
    value = params.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


def _edit_error_to_output(
    exc: EditError, file_path: str, extra_details: dict[str, Any] | None = None
) -> dict[str, Any]:
    details: dict[str, Any] = {
        "attempted_strategies": exc.attempted,
        "error": exc.args[0],
    }
    if extra_details:
        details.update(extra_details)
    return error_output(
        message=f"Could not find matching code in '{file_path}': {exc.args[0]}",
        suggestion=exc.suggestion
        or "Make sure old_str matches the file exactly, including indentation and whitespace.",
        file_path=file_path,
        details=details,
    )


@tool_retry
async def patch_file_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Apply a single search/replace edit with multi-strategy matching.

    Strategy pipeline (in order): exact -> flexible whitespace ->
    Levenshtein fuzzy -> LLM repair (optional). See
    :mod:`fuzzy_editor` for the full algorithm.
    """
    file_path = params.get("file_path")
    old_str, new_str = _resolve_strings(params)

    if not file_path:
        raise ValueError("file_path parameter is required")
    if old_str is None:
        raise ValueError("old_str parameter is required")
    if new_str is None:
        raise ValueError("new_str parameter is required")

    expected_occurrence = _int_param(params, "expected_occurrence", 1)
    allow_multiple = _bool_param(params, "allow_multiple", False)

    user_id = context.get("user_id")
    project_id_raw = context.get("project_id")
    project_id = str(project_id_raw) if project_id_raw is not None else ""
    project_slug = context.get("project_slug")
    container_directory = context.get("container_directory")
    container_name = context.get("container_name")

    logger.info(
        "[PATCH-FILE] Patching '%s' (expected=%d, allow_multiple=%s)",
        file_path,
        expected_occurrence,
        allow_multiple,
    )

    volume_hints = {
        "volume_id": context.get("volume_id"),
        "cache_node": context.get("cache_node"),
    }

    orchestrator = get_orchestrator()
    try:
        current_content = await orchestrator.read_file(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            file_path=file_path,
            project_slug=project_slug,
            subdir=container_directory,
            **volume_hints,
        )
    except Exception as exc:
        logger.error("[PATCH-FILE] Failed to read '%s': %s", file_path, exc)
        current_content = None

    if current_content is None:
        return error_output(
            message=f"File '{file_path}' does not exist",
            suggestion=(
                "Use write_file to create new files, or list the directory first "
                "to verify the path."
            ),
            file_path=file_path,
        )

    repair_fn = None if context.get("disable_llm_repair") else llm_repair

    try:
        result: EditResult = await apply_edit(
            content=current_content,
            old_str=old_str,
            new_str=new_str,
            expected_occurrence=expected_occurrence,
            allow_multiple=allow_multiple,
            file_path=file_path,
            repair_fn=repair_fn,
        )
    except EditError as exc:
        return _edit_error_to_output(exc, file_path)

    # Record BEFORE mutating so undo can always restore.
    await EDIT_HISTORY.record(file_path, current_content, "edit")

    try:
        success = await orchestrator.write_file(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            file_path=file_path,
            content=result.content,
            project_slug=project_slug,
            subdir=container_directory,
            **volume_hints,
        )
        if not success:
            return error_output(
                message=f"Failed to save patched file '{file_path}'",
                suggestion="Check write permissions and disk space.",
                file_path=file_path,
            )
    except Exception as exc:
        logger.error("[PATCH-FILE] Failed to write '%s': %s", file_path, exc)
        return error_output(
            message=f"Could not save patched file '{file_path}': {exc}",
            suggestion="Check write permissions and retry.",
            file_path=file_path,
            details={"error": str(exc)},
        )

    diff_preview = _generate_diff_preview(current_content, result.content)

    return success_output(
        message=(
            f"Patched '{file_path}' via {result.strategy} match"
            + (" (LLM-repaired)" if result.repair_applied else "")
        ),
        file_path=file_path,
        diff=diff_preview,
        details={
            "strategy": result.strategy,
            "match_method": result.strategy,
            "occurrences": result.occurrences,
            "repair_applied": result.repair_applied,
            "size_bytes": len(result.content),
        },
    )


@tool_retry
async def multi_edit_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Apply multiple search/replace edits to a single file in sequence.

    Each edit runs through the full three-strategy pipeline and operates
    on the buffer produced by the previous edit. One :data:`EDIT_HISTORY`
    entry is recorded per successful edit so each one can be undone
    independently.
    """
    file_path = params.get("file_path")
    edits = params.get("edits", [])

    if not file_path:
        raise ValueError("file_path parameter is required")
    if not isinstance(edits, list) or not edits:
        raise ValueError("edits parameter is required and must be a non-empty list")

    user_id = context.get("user_id")
    project_id_raw = context.get("project_id")
    project_id = str(project_id_raw) if project_id_raw is not None else ""
    project_slug = context.get("project_slug")
    container_directory = context.get("container_directory")
    container_name = context.get("container_name")

    logger.info(
        "[MULTI-EDIT] '%s' with %d edit(s) (subdir=%s)",
        file_path,
        len(edits),
        container_directory,
    )

    volume_hints = {
        "volume_id": context.get("volume_id"),
        "cache_node": context.get("cache_node"),
    }

    orchestrator = get_orchestrator()
    try:
        current_content = await orchestrator.read_file(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            file_path=file_path,
            project_slug=project_slug,
            subdir=container_directory,
            **volume_hints,
        )
    except Exception as exc:
        logger.error("[MULTI-EDIT] Failed to read '%s': %s", file_path, exc)
        current_content = None

    if current_content is None:
        return error_output(
            message=f"File '{file_path}' does not exist",
            suggestion="Use write_file to create new files, or list the directory first.",
            file_path=file_path,
        )

    repair_fn = None if context.get("disable_llm_repair") else llm_repair

    buffer = current_content
    applied: list[dict[str, Any]] = []

    for i, edit in enumerate(edits):
        old_str, new_str = _resolve_strings(edit)
        if old_str is None or new_str is None:
            return error_output(
                message=(f"Edit {i + 1} is missing 'search' or 'replace' (old_str/new_str) field"),
                suggestion="Every edit must include both old_str and new_str.",
                file_path=file_path,
                details={"edit_index": i, "applied": applied},
            )

        expected_occurrence = _int_param(edit, "expected_occurrence", 1)
        allow_multiple = _bool_param(edit, "allow_multiple", False)

        # Record BEFORE the mutation so each step is independently undoable.
        await EDIT_HISTORY.record(file_path, buffer, "edit")

        try:
            result = await apply_edit(
                content=buffer,
                old_str=old_str,
                new_str=new_str,
                expected_occurrence=expected_occurrence,
                allow_multiple=allow_multiple,
                file_path=file_path,
                repair_fn=repair_fn,
            )
        except EditError as exc:
            await EDIT_HISTORY.pop_latest(file_path)
            base = _edit_error_to_output(
                exc,
                file_path,
                extra_details={
                    "edit_index": i,
                    "applied": applied,
                    "applied_edits": applied,
                },
            )
            base["message"] = f"Edit {i + 1}/{len(edits)} failed: {base['message']}"
            return base

        buffer = result.content
        applied.append(
            {
                "index": i,
                "strategy": result.strategy,
                "occurrences": result.occurrences,
                "repair_applied": result.repair_applied,
            }
        )

    try:
        success = await orchestrator.write_file(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            file_path=file_path,
            content=buffer,
            project_slug=project_slug,
            subdir=container_directory,
            **volume_hints,
        )
        if not success:
            return error_output(
                message=f"Failed to save edited file '{file_path}'",
                suggestion="Check write permissions and disk space.",
                file_path=file_path,
            )
    except Exception as exc:
        logger.error("[MULTI-EDIT] Failed to write '%s': %s", file_path, exc)
        return error_output(
            message=f"Could not save edited file '{file_path}': {exc}",
            suggestion="Check write permissions and retry.",
            file_path=file_path,
            details={"error": str(exc), "applied": applied},
        )

    diff_preview = _generate_diff_preview(current_content, buffer)

    return success_output(
        message=f"Applied {len(applied)} edit(s) to '{file_path}'",
        file_path=file_path,
        diff=diff_preview,
        details={
            "edit_count": len(applied),
            "applied": applied,
            "applied_edits": applied,
            "size_bytes": len(buffer),
        },
    )


def register_edit_tools(registry) -> None:
    """Register ``patch_file`` and ``multi_edit`` tools."""

    registry.register(
        Tool(
            name="patch_file",
            description=(
                "Apply a surgical edit to an existing file using search/replace. "
                "Uses a multi-strategy matcher (exact -> whitespace-flexible -> "
                "Levenshtein fuzzy) with optional LLM repair for failed matches."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file relative to project root",
                    },
                    "old_str": {
                        "type": "string",
                        "description": (
                            "Exact text to find (include 3-5 lines of context for uniqueness)."
                        ),
                    },
                    "new_str": {
                        "type": "string",
                        "description": "Replacement text.",
                    },
                    "expected_occurrence": {
                        "type": "integer",
                        "description": (
                            "Number of occurrences you expect to replace. Defaults to 1."
                        ),
                    },
                    "allow_multiple": {
                        "type": "boolean",
                        "description": ("When true, replace every match regardless of count."),
                    },
                },
                "required": ["file_path", "old_str", "new_str"],
            },
            executor=patch_file_tool,
            category=ToolCategory.FILE_OPS,
            examples=[
                '{"tool_name": "patch_file", "parameters": {"file_path": "src/App.jsx", "old_str": "bg-blue-500", "new_str": "bg-green-500"}}',
            ],
        )
    )

    registry.register(
        Tool(
            name="multi_edit",
            description=(
                "Apply multiple search/replace edits to a single file in sequence. "
                "Each edit runs through the full multi-strategy matcher and sees "
                "the buffer produced by the previous edit."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file relative to project root",
                    },
                    "edits": {
                        "type": "array",
                        "description": ("List of search/replace operations, applied in order."),
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_str": {"type": "string"},
                                "new_str": {"type": "string"},
                                "expected_occurrence": {"type": "integer"},
                                "allow_multiple": {"type": "boolean"},
                            },
                            "required": ["old_str", "new_str"],
                        },
                    },
                },
                "required": ["file_path", "edits"],
            },
            executor=multi_edit_tool,
            category=ToolCategory.FILE_OPS,
            examples=[
                '{"tool_name": "multi_edit", "parameters": {"file_path": "src/App.jsx", "edits": [{"old_str": "useState(0)", "new_str": "useState(10)"}, {"old_str": "bg-blue-500", "new_str": "bg-green-500"}]}}',
            ],
        )
    )

    logger.info("Registered 2 file edit tools")
