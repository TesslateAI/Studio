"""
git_log Tool

Parses ``git log`` output into structured per-commit dicts.

Uses a custom ``--pretty=format`` string with explicit ASCII record
separators (``\\x1e`` between fields, ``\\x1f`` between commits) so the
parser never needs to reason about escaped quotes inside commit messages.
"""

from __future__ import annotations

import logging
from typing import Any

from ..output_formatter import error_output, pluralize, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)

# Record separators.
_FIELD_SEP = "\x1e"  # Between fields within a commit record.
_COMMIT_SEP = "\x1f"  # Between commit records.

# Fields produced by the pretty-format string, in order.
_LOG_FIELDS = (
    "hash",
    "abbrev",
    "author_name",
    "author_email",
    "author_date",
    "subject",
    "body",
    "refs",
)

# ``%x1e`` / ``%x1f`` emit the literal record-separator bytes in git's
# pretty-format mini-language. The trailing ``%x1f`` terminates each
# commit so the parser can ``split`` on it unambiguously.
_LOG_FORMAT = (
    "%H" + "%x1e"  # hash
    "%h" + "%x1e"  # abbrev
    "%an" + "%x1e"  # author name
    "%ae" + "%x1e"  # author email
    "%aI" + "%x1e"  # author date (ISO 8601 strict)
    "%s" + "%x1e"  # subject
    "%b" + "%x1e"  # body
    "%D" + "%x1f"  # refs + commit terminator
)


def _parse_log_output(raw: str) -> list[dict[str, Any]]:
    """
    Split ``raw`` into structured commit records.

    Args:
        raw: Stdout of ``git log`` invoked with ``_LOG_FORMAT``.

    Returns:
        List of commit dicts — see ``git_log_tool`` for the shape.
    """
    commits: list[dict[str, Any]] = []
    # Each commit is terminated by _COMMIT_SEP, so splitting on it yields
    # one extra trailing empty segment which we discard.
    for record in raw.split(_COMMIT_SEP):
        if not record.strip():
            continue
        fields = record.split(_FIELD_SEP)
        if len(fields) < len(_LOG_FIELDS):
            # Malformed record — skip silently rather than blow up the whole batch.
            logger.warning(
                "[GIT-LOG] Skipping malformed record with %d fields: %r",
                len(fields),
                record[:120],
            )
            continue

        # Strip leading newlines introduced by the commit separator sitting
        # right before the next record.
        values = [f.lstrip("\n") for f in fields[: len(_LOG_FIELDS)]]
        commit = dict(zip(_LOG_FIELDS, values, strict=True))

        commits.append(
            {
                "hash": commit["hash"],
                "abbrev": commit["abbrev"],
                "author": {
                    "name": commit["author_name"],
                    "email": commit["author_email"],
                },
                "date": commit["author_date"],
                "subject": commit["subject"],
                "body": commit["body"].rstrip("\n"),
                "refs": commit["refs"],
            }
        )

    return commits


async def git_log_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Run ``git log`` and return parsed commit records.

    Args:
        params:
            path: Optional path filter — only show commits touching this path.
            max_count: Maximum number of commits to return. Default: 50.
            author: Filter to commits with this author substring.
            since: Only commits after this date (any format ``git log --since`` accepts).
            until: Only commits before this date.
            grep: Filter to commits whose message matches this pattern.
        context: Standard tool execution context.

    Returns:
        ``{"commits": [...], "count": int}`` on success, an error dict otherwise.
    """
    path = params.get("path")
    max_count = int(params.get("max_count", 50))
    author = params.get("author")
    since = params.get("since")
    until = params.get("until")
    grep = params.get("grep")

    if max_count <= 0:
        return error_output(
            message="max_count must be a positive integer",
            suggestion="Pass max_count >= 1, e.g. 20",
            details={"max_count": max_count},
        )

    command: list[str] = [
        "git",
        "log",
        f"--max-count={max_count}",
        "--date=iso-strict",
        f"--pretty=format:{_LOG_FORMAT}",
    ]
    if author:
        command.append(f"--author={author}")
    if since:
        command.append(f"--since={since}")
    if until:
        command.append(f"--until={until}")
    if grep:
        command.append(f"--grep={grep}")

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
        logger.error("[GIT-LOG] execute_command failed: %s", exc)
        return error_output(
            message="git log failed to execute",
            suggestion="Verify the project directory is a git repository",
            details={"error": str(exc)},
        )

    commits = _parse_log_output(raw)

    return success_output(
        message=f"Returned {pluralize(len(commits), 'commit')}",
        commits=commits,
        count=len(commits),
    )


def register_git_log_tool(registry) -> None:
    """Register the git_log tool with the provided registry."""
    registry.register(
        Tool(
            name="git_log",
            description=(
                "Read commit history from the project's git repository. Returns "
                "a structured list of commits with hash, author, date, subject, "
                "body, and refs. Supports path, author, date range, and grep filters."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Restrict history to commits touching this path (optional).",
                    },
                    "max_count": {
                        "type": "integer",
                        "description": "Maximum number of commits to return. Default 50.",
                    },
                    "author": {
                        "type": "string",
                        "description": "Filter commits by author substring (optional).",
                    },
                    "since": {
                        "type": "string",
                        "description": "Only commits after this date (e.g. '2 weeks ago', '2024-01-01').",
                    },
                    "until": {
                        "type": "string",
                        "description": "Only commits before this date.",
                    },
                    "grep": {
                        "type": "string",
                        "description": "Filter commits whose message matches this pattern.",
                    },
                },
                "required": [],
            },
            executor=git_log_tool,
            category=ToolCategory.GIT_OPS,
            examples=[
                '{"tool_name": "git_log", "parameters": {"max_count": 10}}',
                '{"tool_name": "git_log", "parameters": {"path": "src/App.jsx", "max_count": 5}}',
                '{"tool_name": "git_log", "parameters": {"author": "alice", "since": "1 week ago"}}',
            ],
        )
    )
    logger.info("Registered git_log tool")
