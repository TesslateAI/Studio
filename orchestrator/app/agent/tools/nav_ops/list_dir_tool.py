"""
List Directory Tool

Bounded-depth directory tree listing with pagination. Returns a flat list of
``{name, path, type, size, depth}`` entries suitable for a tree-style
renderer. Entry names longer than ``MAX_ENTRY_LENGTH`` characters are
truncated with an ellipsis and flagged via ``truncated_name``.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

from ..output_formatter import error_output, pluralize, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


MAX_ENTRY_LENGTH = 500
DEFAULT_OFFSET = 1
DEFAULT_LIMIT = 25
DEFAULT_DEPTH = 2
MAX_DEPTH = 16
MAX_LIMIT = 500


def _truncate_name(name: str) -> tuple[str, bool]:
    """Truncate ``name`` to ``MAX_ENTRY_LENGTH`` characters if needed."""
    if len(name) <= MAX_ENTRY_LENGTH:
        return name, False
    # Reserve one character for the ellipsis marker.
    return name[: MAX_ENTRY_LENGTH - 1] + "\u2026", True


def _join(parent: str, child: str) -> str:
    """Join two path components with a forward slash."""
    if not parent or parent in (".", "./"):
        return child
    return parent.rstrip("/") + "/" + child


async def list_dir_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    List a directory tree up to ``depth`` levels, sliced by ``offset`` / ``limit``.

    Args:
        params: ``{dir_path, offset?, limit?, depth?, include_hidden?}``
        context: Standard tool execution context.

    Returns:
        Standard success/error dict with an ``entries`` list.
    """
    dir_path = params.get("dir_path")
    if dir_path is None:
        return error_output(
            message="dir_path parameter is required",
            suggestion="Pass a directory path relative to the project root (use '.' for the root)",
        )

    offset_raw = params.get("offset", DEFAULT_OFFSET)
    limit_raw = params.get("limit", DEFAULT_LIMIT)
    depth_raw = params.get("depth", DEFAULT_DEPTH)
    include_hidden = bool(params.get("include_hidden", False))

    try:
        offset = int(offset_raw)
    except (TypeError, ValueError):
        offset = DEFAULT_OFFSET
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    try:
        depth = int(depth_raw)
    except (TypeError, ValueError):
        depth = DEFAULT_DEPTH

    if offset < 1:
        return error_output(
            message="offset must be a 1-indexed entry number",
            suggestion="Pass offset >= 1 (the first entry is offset=1)",
        )
    if limit < 1:
        return error_output(
            message="limit must be greater than zero",
            suggestion="Pass a positive limit, or omit it for the default",
        )
    if depth < 1:
        return error_output(
            message="depth must be greater than zero",
            suggestion="Pass depth >= 1",
        )

    limit = min(limit, MAX_LIMIT)
    depth = min(depth, MAX_DEPTH)

    user_id = context["user_id"]
    project_id = str(context["project_id"])
    container_name = context.get("container_name")

    logger.info(
        "[LIST-DIR] dir_path=%r offset=%s limit=%s depth=%s include_hidden=%s",
        dir_path,
        offset,
        limit,
        depth,
        include_hidden,
    )

    from ....services.orchestration import get_orchestrator

    orchestrator = get_orchestrator()

    # Bounded BFS through list_files, capped by ``depth`` levels.
    entries: list[dict[str, Any]] = []
    queue: deque[tuple[str, int]] = deque()
    queue.append((dir_path, 0))

    try:
        root_listing = await orchestrator.list_files(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            directory=dir_path,
        )
    except Exception as exc:
        logger.error("[LIST-DIR] list_files failed at root %r: %s", dir_path, exc)
        return error_output(
            message=f"Failed to list directory '{dir_path}': {exc}",
            suggestion="Verify that dir_path exists inside the project root",
        )

    # Determine if dir_path looks valid: list_files returns [] for missing dirs,
    # so an empty root plus a missing path looks the same as an empty directory.
    # We accept both as "no entries" rather than erroring.

    # Seed the traversal with the root listing so we don't have to re-read it.
    _seeded: dict[str, list[dict[str, Any]]] = {dir_path: root_listing}

    visited: set[str] = set()

    while queue:
        current_dir, current_depth = queue.popleft()
        if current_dir in visited:
            continue
        visited.add(current_dir)

        if current_dir in _seeded:
            listing = _seeded.pop(current_dir)
        else:
            try:
                listing = await orchestrator.list_files(
                    user_id=user_id,
                    project_id=project_id,
                    container_name=container_name,
                    directory=current_dir,
                )
            except Exception as exc:
                logger.warning("[LIST-DIR] list_files failed for %r: %s", current_dir, exc)
                continue

        sorted_listing = sorted(listing, key=lambda e: e.get("name", ""))

        for item in sorted_listing:
            name = item.get("name") or ""
            if not include_hidden and name.startswith("."):
                continue

            entry_type = item.get("type")
            is_dir = entry_type == "directory"
            rel_path = item.get("path") or _join(current_dir, name)

            display_name, was_truncated = _truncate_name(name)
            record: dict[str, Any] = {
                "name": display_name,
                "path": rel_path,
                "type": "directory" if is_dir else "file",
                "size": int(item.get("size", 0) or 0),
                "depth": current_depth,
            }
            if was_truncated:
                record["truncated_name"] = True
            entries.append(record)

            if is_dir and current_depth + 1 < depth:
                queue.append((rel_path, current_depth + 1))

    total = len(entries)

    if total == 0:
        return success_output(
            message=f"Directory '{dir_path}' has no entries",
            entries=[],
            total=0,
            details={"dir_path": dir_path, "depth": depth},
        )

    start = offset - 1
    if start >= total:
        return error_output(
            message="offset exceeds directory entry count",
            suggestion=f"Pass offset between 1 and {total}",
            details={"total": total, "offset": offset},
        )

    end = start + limit
    sliced = entries[start:end]
    has_more = end < total

    summary = f"Listed {pluralize(len(sliced), 'entry', 'entries')} under '{dir_path}'"
    if has_more:
        summary += f" (showing {start + 1}-{end} of {total})"

    return success_output(
        message=summary,
        entries=sliced,
        total=total,
        has_more=has_more,
        details={
            "dir_path": dir_path,
            "offset": offset,
            "limit": limit,
            "depth": depth,
            "include_hidden": include_hidden,
        },
    )


def register_list_dir_tool(registry) -> None:
    """Register the list_dir navigation tool."""

    registry.register(
        Tool(
            name="list_dir",
            description=(
                "Bounded-depth directory tree listing with pagination. Returns "
                "a flat list of entries with their name, path, type, size, and "
                "indentation depth. Useful for rendering a tree view without "
                "walking huge subtrees."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "dir_path": {
                        "type": "string",
                        "description": "Directory path relative to the project root (use '.' for the root)",
                    },
                    "offset": {
                        "type": "integer",
                        "description": f"1-indexed starting entry number (default: {DEFAULT_OFFSET})",
                    },
                    "limit": {
                        "type": "integer",
                        "description": f"Maximum number of entries to return (default: {DEFAULT_LIMIT}, max: {MAX_LIMIT})",
                    },
                    "depth": {
                        "type": "integer",
                        "description": f"Recursion depth (default: {DEFAULT_DEPTH}, max: {MAX_DEPTH})",
                    },
                    "include_hidden": {
                        "type": "boolean",
                        "description": "Include dotfiles and dot-directories (default: false)",
                    },
                },
                "required": ["dir_path"],
            },
            executor=list_dir_tool,
            category=ToolCategory.NAV_OPS,
            examples=[
                '{"tool_name": "list_dir", "parameters": {"dir_path": "."}}',
                '{"tool_name": "list_dir", "parameters": {"dir_path": "src", "depth": 3, "limit": 50}}',
                '{"tool_name": "list_dir", "parameters": {"dir_path": ".", "offset": 26, "limit": 25}}',
            ],
        )
    )
