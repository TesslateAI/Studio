"""
git_diff Tool

Runs ``git diff`` in one of four modes and parses the unified-diff output
into a structured per-file, per-hunk representation.

Modes:
    - base and target set    -> ``git diff <base>..<target>``
    - base only              -> ``git diff <base>``
    - staged=True            -> ``git diff --cached``
    - default                -> ``git diff`` (unstaged worktree changes)
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)

# "@@ -<old_start>[,<old_lines>] +<new_start>[,<new_lines>] @@ <section heading>"
_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_lines>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_lines>\d+))? @@"
)


def _parse_unified_diff(raw: str) -> dict[str, Any]:
    """
    Parse a unified diff into ``{"files": [...], "stats": {...}}``.

    Each file dict contains ``path``, ``old_path``, and a list of hunks.
    Each hunk contains ``old_start``, ``old_lines``, ``new_start``,
    ``new_lines``, and a list of line dicts with type
    ``"context" | "addition" | "deletion"``.
    """
    files: list[dict[str, Any]] = []
    current_file: dict[str, Any] | None = None
    current_hunk: dict[str, Any] | None = None

    insertions = 0
    deletions = 0

    lines = raw.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("diff --git "):
            # "diff --git a/<old> b/<new>"
            current_file = {
                "path": None,
                "old_path": None,
                "hunks": [],
            }
            files.append(current_file)
            current_hunk = None
            # Path pair parsed from the diff header. The subsequent
            # "---" / "+++" lines provide the authoritative paths.
            parts = line[len("diff --git ") :].split(" ", 1)
            if len(parts) == 2:
                a_path = parts[0][2:] if parts[0].startswith("a/") else parts[0]
                b_path = parts[1][2:] if parts[1].startswith("b/") else parts[1]
                current_file["old_path"] = a_path
                current_file["path"] = b_path
            i += 1
            continue

        if current_file is not None:
            if line.startswith("--- "):
                src = line[4:]
                if src.startswith("a/"):
                    current_file["old_path"] = src[2:]
                elif src == "/dev/null":
                    current_file["old_path"] = None
                else:
                    current_file["old_path"] = src
                i += 1
                continue

            if line.startswith("+++ "):
                dst = line[4:]
                if dst.startswith("b/"):
                    current_file["path"] = dst[2:]
                elif dst == "/dev/null":
                    current_file["path"] = None
                else:
                    current_file["path"] = dst
                i += 1
                continue

            header_match = _HUNK_HEADER_RE.match(line)
            if header_match is not None:
                current_hunk = {
                    "old_start": int(header_match.group("old_start")),
                    "old_lines": int(header_match.group("old_lines") or 1),
                    "new_start": int(header_match.group("new_start")),
                    "new_lines": int(header_match.group("new_lines") or 1),
                    "lines": [],
                }
                current_file["hunks"].append(current_hunk)
                i += 1
                continue

            if current_hunk is not None:
                if line.startswith("+") and not line.startswith("+++"):
                    current_hunk["lines"].append({"type": "addition", "text": line[1:]})
                    insertions += 1
                    i += 1
                    continue
                if line.startswith("-") and not line.startswith("---"):
                    current_hunk["lines"].append({"type": "deletion", "text": line[1:]})
                    deletions += 1
                    i += 1
                    continue
                if line.startswith(" "):
                    current_hunk["lines"].append({"type": "context", "text": line[1:]})
                    i += 1
                    continue
                if line.startswith("\\"):
                    # "\ No newline at end of file" — annotation, skip.
                    i += 1
                    continue

        i += 1

    stats = {
        "files_changed": len(files),
        "insertions": insertions,
        "deletions": deletions,
    }
    return {"files": files, "stats": stats}


async def git_diff_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Run ``git diff`` and return the parsed unified diff.

    Args:
        params:
            path: Optional path filter.
            staged: If True, diff the index against HEAD.
            base: Optional ref. Diff against this ref, or against target if set.
            target: Optional ref. Diff from base..target.
            unified: Unified context line count. Default 3.
        context: Standard tool execution context.

    Returns:
        ``{"files": [...], "stats": {...}, "raw": str}`` on success.
    """
    path = params.get("path")
    staged = bool(params.get("staged", False))
    base = params.get("base")
    target = params.get("target")
    unified = int(params.get("unified", 3))

    if unified < 0:
        return error_output(
            message="unified must be a non-negative integer",
            details={"unified": unified},
        )

    command: list[str] = ["git", "diff", f"-U{unified}"]
    if base and target:
        command.append(f"{base}..{target}")
    elif base:
        command.append(base)
    elif staged:
        command.append("--cached")
    # Else: plain ``git diff`` — unstaged worktree changes.

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
        logger.error("[GIT-DIFF] execute_command failed: %s", exc)
        return error_output(
            message="git diff failed to execute",
            suggestion="Verify the project is a git repository and the refs exist",
            details={"error": str(exc)},
        )

    if raw.lstrip().startswith("fatal:"):
        return error_output(
            message=f"git diff refused: {raw.strip().splitlines()[0]}",
            suggestion="Check that the provided refs and paths exist",
            details={"output": raw},
        )

    parsed = _parse_unified_diff(raw)
    files_changed = parsed["stats"]["files_changed"]

    message = (
        "No differences"
        if files_changed == 0
        else f"{files_changed} file(s) changed "
        f"(+{parsed['stats']['insertions']} -{parsed['stats']['deletions']})"
    )

    return success_output(
        message=message,
        files=parsed["files"],
        stats=parsed["stats"],
        raw=raw,
    )


def register_git_diff_tool(registry) -> None:
    """Register the git_diff tool with the provided registry."""
    registry.register(
        Tool(
            name="git_diff",
            description=(
                "Run git diff and return the parsed unified diff: per-file hunks "
                "with typed lines (context/addition/deletion) and aggregate stats. "
                "Supports worktree, staged, single-ref, and base..target diffs."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Restrict diff to this path (optional).",
                    },
                    "staged": {
                        "type": "boolean",
                        "description": "Diff the index against HEAD. Ignored if base is set.",
                    },
                    "base": {
                        "type": "string",
                        "description": "Base ref. With target: diff base..target. Alone: diff HEAD against base.",
                    },
                    "target": {
                        "type": "string",
                        "description": "Target ref. Requires base. Produces base..target diff.",
                    },
                    "unified": {
                        "type": "integer",
                        "description": "Unified context line count (maps to -U). Default 3.",
                    },
                },
                "required": [],
            },
            executor=git_diff_tool,
            category=ToolCategory.GIT_OPS,
            # Diff filter params in, unified diff text out — JSON-clean.
            state_serializable=True,
            # Read-only git invocation.
            holds_external_state=False,
            examples=[
                '{"tool_name": "git_diff", "parameters": {}}',
                '{"tool_name": "git_diff", "parameters": {"staged": true}}',
                '{"tool_name": "git_diff", "parameters": {"base": "main", "target": "feature/new-ui"}}',
                '{"tool_name": "git_diff", "parameters": {"path": "src/App.jsx", "unified": 5}}',
            ],
        )
    )
    logger.info("Registered git_diff tool")
