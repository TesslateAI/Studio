"""
git_blame Tool

Parses the output of ``git blame --line-porcelain`` into a structured
per-line list: each line carries the commit it came from, the author,
the timestamp, the commit subject, and the line contents.
"""

from __future__ import annotations

import logging
from typing import Any

from ..output_formatter import error_output, pluralize, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


def _parse_blame_porcelain(raw: str) -> list[dict[str, Any]]:
    """
    Parse ``git blame --line-porcelain`` output into per-line records.

    Porcelain format layout (one block per blamed line)::

        <sha> <orig-line> <final-line> [<group-size>]
        author <name>
        author-mail <email>
        author-time <unix-ts>
        author-tz <offset>
        committer <name>
        committer-mail <email>
        committer-time <unix-ts>
        committer-tz <offset>
        summary <subject>
        ...
        filename <path>
        \t<line contents>

    ``--line-porcelain`` repeats the full author block for every line
    (no de-duping across groups), so we can parse one line at a time
    without remembering previous commits.
    """
    lines: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for line in raw.split("\n"):
        if current is None:
            if not line.strip():
                continue
            # Header: "<sha> <orig> <final> [<group>]"
            header = line.split(" ")
            if len(header) < 3:
                # Not a blame header — ignore stray output.
                continue
            sha = header[0]
            try:
                final_lineno = int(header[2])
            except ValueError:
                continue
            current = {
                "hash": sha,
                "abbrev": sha[:7],
                "line_number": final_lineno,
                "author": "",
                "author_mail": "",
                "author_time": "",
                "summary": "",
                "content": "",
            }
            continue

        if line.startswith("\t"):
            # The blamed line content — terminates the current record.
            current["content"] = line[1:]
            lines.append(current)
            current = None
            continue

        if line.startswith("author "):
            current["author"] = line[len("author ") :]
        elif line.startswith("author-mail "):
            current["author_mail"] = line[len("author-mail ") :].strip("<>")
        elif line.startswith("author-time "):
            current["author_time"] = line[len("author-time ") :]
        elif line.startswith("summary "):
            current["summary"] = line[len("summary ") :]
        # Remaining headers (committer, filename, previous, boundary, ...)
        # are intentionally ignored — they aren't exposed by this tool.

    return lines


async def git_blame_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Run ``git blame`` on a single file and return structured per-line info.

    Args:
        params:
            file_path: Path to the file (required).
            line_start: Optional 1-indexed start line for ``-L``.
            line_end: Optional 1-indexed end line for ``-L``.
        context: Standard tool execution context.

    Returns:
        ``{"file": str, "lines": [...]}`` on success, an error dict otherwise.
    """
    file_path = params.get("file_path")
    if not file_path:
        return error_output(
            message="file_path parameter is required",
            suggestion="Pass the relative path of the file you want to blame",
        )

    line_start = params.get("line_start")
    line_end = params.get("line_end")

    if line_start is not None or line_end is not None:
        if line_start is None or line_end is None:
            return error_output(
                message="line_start and line_end must be provided together",
                suggestion="Either omit both (to blame the full file) or provide both",
            )
        try:
            line_start_int = int(line_start)
            line_end_int = int(line_end)
        except (TypeError, ValueError):
            return error_output(
                message="line_start and line_end must be integers",
                details={"line_start": line_start, "line_end": line_end},
            )
        if line_start_int < 1 or line_end_int < line_start_int:
            return error_output(
                message="Invalid line range",
                suggestion="line_start must be >= 1 and line_end must be >= line_start",
                details={"line_start": line_start_int, "line_end": line_end_int},
            )
        range_arg = f"{line_start_int},{line_end_int}"
    else:
        range_arg = None

    command: list[str] = ["git", "blame", "--line-porcelain"]
    if range_arg:
        command.extend(["-L", range_arg])
    command.extend(["--", file_path])

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
        logger.error("[GIT-BLAME] execute_command failed: %s", exc)
        return error_output(
            message="git blame failed to execute",
            suggestion="Verify the project is a git repository and the file is tracked",
            details={"error": str(exc), "file_path": file_path},
        )

    if raw.startswith("fatal:") or "no such path" in raw.lower():
        return error_output(
            message=f"git blame refused: {raw.strip().splitlines()[0]}",
            suggestion="Check that the file exists in the repository and is tracked",
            details={"file_path": file_path, "output": raw},
        )

    lines = _parse_blame_porcelain(raw)

    return success_output(
        message=f"Blamed {pluralize(len(lines), 'line')} in '{file_path}'",
        file=file_path,
        lines=lines,
    )


def register_git_blame_tool(registry) -> None:
    """Register the git_blame tool with the provided registry."""
    registry.register(
        Tool(
            name="git_blame",
            description=(
                "Run git blame on a file (or line range) and return structured "
                "per-line commit attribution: hash, author, timestamp, subject, "
                "and line content."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file to blame, relative to project root.",
                    },
                    "line_start": {
                        "type": "integer",
                        "description": "Optional 1-indexed start line (requires line_end).",
                    },
                    "line_end": {
                        "type": "integer",
                        "description": "Optional 1-indexed end line (requires line_start).",
                    },
                },
                "required": ["file_path"],
            },
            executor=git_blame_tool,
            category=ToolCategory.GIT_OPS,
            examples=[
                '{"tool_name": "git_blame", "parameters": {"file_path": "src/App.jsx"}}',
                '{"tool_name": "git_blame", "parameters": {"file_path": "README.md", "line_start": 1, "line_end": 10}}',
            ],
        )
    )
    logger.info("Registered git_blame tool")
