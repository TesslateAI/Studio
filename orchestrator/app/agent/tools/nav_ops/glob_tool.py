"""
Glob Tool

Fast file pattern matching against the project tree. Uses the orchestrator's
``list_tree`` to enumerate candidate files (with ``.gitignore`` and baseline
exclusions already applied), then filters them with ``fnmatch`` /
``pathlib.PurePath.match`` and sorts by modification time or name.
"""

from __future__ import annotations

import fnmatch
import logging
from pathlib import PurePosixPath
from typing import Any

from ....services.orchestration import get_orchestrator
from ..output_formatter import (
    error_output,
    pluralize,
    success_output,
)
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


DEFAULT_LIMIT = 200
MAX_LIMIT = 2000


def _matches_pattern(rel_path: str, pattern: str) -> bool:
    """
    Return True when ``rel_path`` matches ``pattern``.

    Supports both single-segment ``fnmatch`` globs (``*.py``) and
    multi-segment glob patterns (``src/**/*.ts``). ``**`` is expanded for
    the PurePath matcher by also trying a normalized single-star variant.
    """
    normalized = rel_path.replace("\\", "/")

    # Single-segment fnmatch against basename and against full path.
    if fnmatch.fnmatch(normalized, pattern):
        return True
    base = normalized.rsplit("/", 1)[-1]
    if fnmatch.fnmatch(base, pattern):
        return True

    # Multi-segment via PurePath.match (uses POSIX semantics).
    try:
        if PurePosixPath(normalized).match(pattern):
            return True
    except (ValueError, TypeError):
        pass

    # Explicit ``**`` handling: treat ``a/**/b`` as a prefix+suffix matcher
    # so dir separators are allowed across the wildcard.
    if "**" in pattern:
        parts = pattern.split("**")
        if len(parts) == 2:
            head, tail = parts
            head = head.rstrip("/")
            tail = tail.lstrip("/")
            head_ok = not head or normalized.startswith(head + "/") or normalized == head
            tail_ok = (
                not tail or fnmatch.fnmatch(normalized, f"*{tail}") or normalized.endswith(tail)
            )
            if head_ok and tail_ok:
                return True

    return False


def _is_under(rel_path: str, directory: str) -> bool:
    """Return True when ``rel_path`` lives under ``directory`` (POSIX style)."""
    if not directory or directory in (".", "./"):
        return True
    norm_dir = directory.replace("\\", "/").strip("/")
    norm_rel = rel_path.replace("\\", "/").strip("/")
    if norm_rel == norm_dir:
        return False
    return norm_rel.startswith(norm_dir + "/")


def _segment_depth(rel_path: str, directory: str) -> int:
    """Return how many path segments ``rel_path`` has below ``directory``."""
    norm_rel = rel_path.replace("\\", "/").strip("/")
    if not directory or directory in (".", "./"):
        return norm_rel.count("/")
    norm_dir = directory.replace("\\", "/").strip("/")
    rest = norm_rel[len(norm_dir) + 1 :] if norm_rel.startswith(norm_dir + "/") else norm_rel
    return rest.count("/")


async def glob_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Enumerate files matching a glob pattern, ordered by recency or name.

    Args:
        params: ``{pattern, path?, recursive?, limit?, include_hidden?, sort?}``
        context: Standard tool execution context.

    Returns:
        Standard success/error dict with a ``matches`` list of
        ``{path, size, mtime}`` entries.
    """
    pattern = params.get("pattern")
    if not pattern or not isinstance(pattern, str):
        return error_output(
            message="pattern parameter is required",
            suggestion="Pass a glob pattern such as '**/*.py' or 'src/*.ts'",
        )

    path_param = params.get("path") or "."
    recursive = params.get("recursive", True)
    include_hidden = params.get("include_hidden", False)
    sort_mode = params.get("sort", "mtime")
    if sort_mode not in ("mtime", "name"):
        return error_output(
            message=f"Invalid sort mode '{sort_mode}'",
            suggestion="sort must be one of 'mtime' or 'name'",
        )

    raw_limit = params.get("limit", DEFAULT_LIMIT)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(1, min(limit, MAX_LIMIT))

    user_id = context["user_id"]
    project_id = str(context["project_id"])
    container_name = context.get("container_name")
    container_directory = context.get("container_directory")

    logger.info(
        "[GLOB] pattern=%r path=%r recursive=%s limit=%s sort=%s",
        pattern,
        path_param,
        recursive,
        limit,
        sort_mode,
    )

    try:
        orchestrator = get_orchestrator()
        tree = await orchestrator.list_tree(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            subdir=container_directory,
        )
    except Exception as exc:
        logger.error("[GLOB] list_tree failed: %s", exc)
        return error_output(
            message=f"Failed to enumerate project tree: {exc}",
            suggestion="Verify the project root is accessible and try again",
        )

    candidates: list[dict[str, Any]] = []
    for entry in tree:
        if entry.get("is_dir"):
            continue
        rel_path = entry.get("path")
        if not rel_path:
            continue
        normalized = rel_path.replace("\\", "/")

        if not include_hidden and any(seg.startswith(".") for seg in normalized.split("/")):
            continue

        if path_param and path_param not in (".", "./") and not _is_under(normalized, path_param):
            continue

        if not recursive and _segment_depth(normalized, path_param) > 0:
            continue

        if not _matches_pattern(normalized, pattern):
            base = normalized.rsplit("/", 1)[-1]
            if not fnmatch.fnmatch(base, pattern):
                continue

        candidates.append(
            {
                "path": normalized,
                "size": int(entry.get("size", 0) or 0),
                "mtime": float(entry.get("mod_time", 0.0) or 0.0),
            }
        )

    if sort_mode == "mtime":
        candidates.sort(key=lambda e: e["mtime"], reverse=True)
    else:
        candidates.sort(key=lambda e: e["path"])

    total_found = len(candidates)
    truncated = total_found > limit
    results = candidates[:limit]

    if total_found == 0:
        return success_output(
            message=f"No files matched pattern '{pattern}'",
            matches=[],
            total_found=0,
            truncated=False,
            details={"pattern": pattern, "path": path_param, "sort": sort_mode},
        )

    summary = f"Found {pluralize(total_found, 'file')} matching '{pattern}'"
    if truncated:
        summary += f" (showing first {limit})"

    return success_output(
        message=summary,
        matches=results,
        total_found=total_found,
        truncated=truncated,
        details={
            "pattern": pattern,
            "path": path_param,
            "sort": sort_mode,
            "recursive": recursive,
            "include_hidden": include_hidden,
            "limit": limit,
        },
    )


def register_glob_tool(registry) -> None:
    """Register the glob navigation tool."""

    registry.register(
        Tool(
            name="glob",
            description=(
                "Fast file pattern matching against the project tree. "
                "Supports single-segment globs ('*.py') and multi-segment "
                "globs ('src/**/*.ts'). Returns files sorted by modification "
                "time (newest first) or name. Honors .gitignore and standard "
                "exclusions (node_modules, .git, dist, build, .venv, etc.)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern to match (e.g. '**/*.py', 'src/*.ts')",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search under, relative to project root (default: '.')",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "When false, only match files directly inside 'path' (default: true)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": f"Maximum number of results (default: {DEFAULT_LIMIT}, max: {MAX_LIMIT})",
                    },
                    "include_hidden": {
                        "type": "boolean",
                        "description": "Include dotfiles and files under dot-directories (default: false)",
                    },
                    "sort": {
                        "type": "string",
                        "description": "'mtime' (newest first) or 'name' (alphabetical). Default: 'mtime'",
                    },
                },
                "required": ["pattern"],
            },
            executor=glob_tool,
            category=ToolCategory.NAV_OPS,
            examples=[
                '{"tool_name": "glob", "parameters": {"pattern": "**/*.py"}}',
                '{"tool_name": "glob", "parameters": {"pattern": "*.ts", "path": "src", "recursive": false}}',
                '{"tool_name": "glob", "parameters": {"pattern": "**/test_*.py", "sort": "name", "limit": 50}}',
            ],
        )
    )
