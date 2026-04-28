"""
git_status Tool

Parses ``git status --porcelain=v2 --branch --show-stash`` into a
structured dict: branch metadata, tracked changes (with index/worktree
status characters), renames/copies (with original path), untracked,
ignored, and stash count.

Reference: git status porcelain v2 format::

    # branch.oid <sha>
    # branch.head <name>
    # branch.upstream <upstream>
    # branch.ab +<ahead> -<behind>
    # stash <count>
    1 XY sub mH mI mW hH hI path
    2 XY sub mH mI mW hH hI X<score> path\t<origPath>
    u XY sub m1 m2 m3 mW h1 h2 h3 path
    ? path
    ! path
"""

from __future__ import annotations

import logging
from typing import Any

from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


def _parse_status_porcelain_v2(raw: str) -> dict[str, Any]:
    """
    Parse ``git status --porcelain=v2 --branch --show-stash`` into a dict.

    The parser is intentionally strict on the prefix character (``#``,
    ``1``, ``2``, ``u``, ``?``, ``!``) and tolerant of trailing whitespace
    and missing optional headers.
    """
    branch: dict[str, Any] = {
        "name": None,
        "upstream": None,
        "ahead": 0,
        "behind": 0,
    }
    changes: list[dict[str, Any]] = []
    untracked: list[str] = []
    ignored: list[str] = []
    stash_count = 0

    for line in raw.split("\n"):
        if not line:
            continue

        if line.startswith("# "):
            header = line[2:]
            if header.startswith("branch.head "):
                branch["name"] = header[len("branch.head ") :].strip() or None
            elif header.startswith("branch.upstream "):
                branch["upstream"] = header[len("branch.upstream ") :].strip() or None
            elif header.startswith("branch.ab "):
                # "+N -M"
                parts = header[len("branch.ab ") :].split()
                for part in parts:
                    if part.startswith("+"):
                        try:
                            branch["ahead"] = int(part[1:])
                        except ValueError:
                            branch["ahead"] = 0
                    elif part.startswith("-"):
                        try:
                            branch["behind"] = int(part[1:])
                        except ValueError:
                            branch["behind"] = 0
            elif header.startswith("stash "):
                try:
                    stash_count = int(header[len("stash ") :].strip())
                except ValueError:
                    stash_count = 0
            # Other headers (branch.oid) are ignored.
            continue

        # Ordinary change: "1 XY sub mH mI mW hH hI path"
        if line.startswith("1 "):
            parts = line[2:].split(" ", 7)
            if len(parts) < 8:
                continue
            xy = parts[0]
            path = parts[7]
            changes.append(
                {
                    "path": path,
                    "index_status": xy[0],
                    "worktree_status": xy[1],
                }
            )
            continue

        # Rename/copy: "2 XY sub mH mI mW hH hI X<score> path\t<origPath>"
        if line.startswith("2 "):
            parts = line[2:].split(" ", 8)
            if len(parts) < 9:
                continue
            xy = parts[0]
            # parts[8] is "<score> path\t<origPath>"
            # The rename detection score field is the first token; the rest
            # contains the path pair separated by a literal tab.
            score_and_paths = parts[8]
            score_split = score_and_paths.split(" ", 1)
            if len(score_split) != 2:
                continue
            path_pair = score_split[1]
            if "\t" in path_pair:
                new_path, original_path = path_pair.split("\t", 1)
            else:
                new_path, original_path = path_pair, None
            changes.append(
                {
                    "path": new_path,
                    "index_status": xy[0],
                    "worktree_status": xy[1],
                    "original_path": original_path,
                }
            )
            continue

        # Unmerged: "u XY sub m1 m2 m3 mW h1 h2 h3 path"
        if line.startswith("u "):
            parts = line[2:].split(" ", 10)
            if len(parts) < 11:
                continue
            xy = parts[0]
            path = parts[10]
            changes.append(
                {
                    "path": path,
                    "index_status": xy[0],
                    "worktree_status": xy[1],
                    "unmerged": True,
                }
            )
            continue

        if line.startswith("? "):
            untracked.append(line[2:])
            continue

        if line.startswith("! "):
            ignored.append(line[2:])
            continue

    return {
        "branch": branch,
        "changes": changes,
        "untracked": untracked,
        "ignored": ignored,
        "stash_count": stash_count,
    }


async def git_status_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Run ``git status --porcelain=v2`` and return a structured snapshot.

    Args:
        params:
            path: Optional path filter — restrict status to this path.
            include_untracked: If False, pass ``-uno``. Default: True.
        context: Standard tool execution context.

    Returns:
        ``{"branch": {...}, "changes": [...], "untracked": [...],
           "ignored": [...], "stash_count": int}`` on success.
    """
    path = params.get("path")
    include_untracked = params.get("include_untracked", True)

    command: list[str] = [
        "git",
        "status",
        "--porcelain=v2",
        "--branch",
        "--show-stash",
    ]
    if not include_untracked:
        command.append("-uno")
    if path:
        command.append("--")
        command.append(path)

    user_id = context["user_id"]
    project_id = str(context["project_id"])
    container_name = context.get("container_name")

    from ....services.orchestration import get_orchestrator

    try:
        orchestrator = get_orchestrator()
        raw = await orchestrator.execute_command(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            command=command,
            timeout=60,
            working_dir=context.get("working_dir"),
        )
    except RuntimeError as exc:
        logger.error("[GIT-STATUS] execute_command failed: %s", exc)
        return error_output(
            message="git status failed to execute",
            suggestion="Verify the project directory is a git repository",
            details={"error": str(exc)},
        )

    if raw.lstrip().startswith("fatal:"):
        return error_output(
            message=f"git status refused: {raw.strip().splitlines()[0]}",
            suggestion="Ensure the working directory is a git repository",
            details={"output": raw},
        )

    parsed = _parse_status_porcelain_v2(raw)

    total_changes = len(parsed["changes"]) + len(parsed["untracked"])
    branch_name = parsed["branch"]["name"] or "(detached)"
    message = (
        f"{total_changes} change(s) on branch '{branch_name}'"
        if total_changes
        else f"Working tree clean on branch '{branch_name}'"
    )

    return success_output(
        message=message,
        branch=parsed["branch"],
        changes=parsed["changes"],
        untracked=parsed["untracked"],
        ignored=parsed["ignored"],
        stash_count=parsed["stash_count"],
    )


def register_git_status_tool(registry) -> None:
    """Register the git_status tool with the provided registry."""
    registry.register(
        Tool(
            name="git_status",
            description=(
                "Show the working tree status (porcelain v2) as structured data: "
                "branch info (name, upstream, ahead/behind), per-file index/worktree "
                "status, untracked files, ignored files, and stash count."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Restrict status to this path (optional).",
                    },
                    "include_untracked": {
                        "type": "boolean",
                        "description": "Include untracked files in the output. Default true.",
                    },
                },
                "required": [],
            },
            executor=git_status_tool,
            category=ToolCategory.GIT_OPS,
            # Optional path/flags in, status dict out — JSON-clean.
            state_serializable=True,
            # Read-only git invocation; no persistent state.
            holds_external_state=False,
            examples=[
                '{"tool_name": "git_status", "parameters": {}}',
                '{"tool_name": "git_status", "parameters": {"include_untracked": false}}',
                '{"tool_name": "git_status", "parameters": {"path": "src/"}}',
            ],
        )
    )
    logger.info("Registered git_status tool")
