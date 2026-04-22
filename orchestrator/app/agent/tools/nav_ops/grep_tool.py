"""
Grep Tool

Content search powered by ``ripgrep``. Shells out to ``rg`` via the
orchestrator's ``execute_command`` interface so the tool works uniformly
across every deployment backend.

Supports three output modes:
    - ``files_with_matches`` (default): returns a list of paths containing
      at least one match.
    - ``count``: returns per-file match counts.
    - ``content``: returns structured match records with line numbers and
      optional context lines.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ....services.orchestration import get_orchestrator
from ..output_formatter import (
    error_output,
    pluralize,
    success_output,
)
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


# Cap on raw bytes returned to callers when the tool is in ``content`` mode.
MAX_CONTENT_BYTES = 256 * 1024  # 256 KiB

VALID_OUTPUT_MODES = ("content", "files_with_matches", "count")


def _coerce_int(value: Any) -> int | None:
    """Convert ``value`` to int, returning ``None`` for missing / invalid input."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _validate_regex(pattern: str) -> str | None:
    """Return an error string if ``pattern`` is not a valid Python regex."""
    try:
        re.compile(pattern)
    except re.error as exc:
        return f"Invalid regular expression '{pattern}': {exc}"
    return None


def _build_rg_args(
    *,
    pattern: str,
    path: str | None,
    include_glob: str | None,
    file_type: str | None,
    output_mode: str,
    i_flag: bool,
    n_flag: bool,
    context_before: int | None,
    context_after: int | None,
    context_both: int | None,
    multiline: bool,
) -> list[str]:
    """Assemble the argv for the ``rg`` invocation."""
    args: list[str] = ["rg", "--color", "never"]

    if i_flag:
        args.append("-i")

    if multiline:
        args.extend(["-U", "--multiline-dotall"])

    if file_type:
        args.extend(["--type", file_type])

    if include_glob:
        args.extend(["-g", include_glob])

    if output_mode == "files_with_matches":
        args.append("--files-with-matches")
    elif output_mode == "count":
        args.append("--count")
    else:  # content
        # Structured JSON output gives us line numbers and optional context.
        args.append("--json")
        if context_both is not None and context_both > 0:
            args.extend(["-C", str(context_both)])
        else:
            if context_before is not None and context_before > 0:
                args.extend(["-B", str(context_before)])
            if context_after is not None and context_after > 0:
                args.extend(["-A", str(context_after)])
        if n_flag:
            args.append("-n")

    args.append("--")
    args.append(pattern)

    if path:
        args.append(path)

    return args


def _parse_files_with_matches(text: str) -> list[str]:
    """Parse plain ``rg --files-with-matches`` output into a list of paths."""
    files: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        files.append(stripped)
    return files


def _parse_count_output(text: str) -> dict[str, int]:
    """Parse ``rg --count`` output (``path:N``) into a mapping."""
    counts: dict[str, int] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        idx = stripped.rfind(":")
        if idx == -1:
            continue
        path = stripped[:idx]
        num = stripped[idx + 1 :]
        try:
            counts[path] = int(num)
        except ValueError:
            continue
    return counts


def _parse_json_output(text: str) -> list[dict[str, Any]]:
    """
    Parse ``rg --json`` newline-delimited output into match records.

    Each record has ``path``, ``line_number``, ``line_text``, and optional
    ``before_context`` / ``after_context`` lists.
    """
    matches: list[dict[str, Any]] = []
    pending_before: list[dict[str, Any]] = []
    last_match_index: int | None = None

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            evt = json.loads(stripped)
        except json.JSONDecodeError:
            continue

        event_type = evt.get("type")
        data = evt.get("data") or {}

        if event_type == "begin":
            pending_before = []
            last_match_index = None
            continue

        if event_type == "end":
            pending_before = []
            last_match_index = None
            continue

        if event_type == "context":
            path_obj = (data.get("path") or {}).get("text") or ""
            line_no = data.get("line_number")
            line_text = (data.get("lines") or {}).get("text") or ""
            line_text = line_text.rstrip("\n")
            context_entry = {"line_number": line_no, "line_text": line_text}
            if last_match_index is not None:
                matches[last_match_index].setdefault("after_context", []).append(context_entry)
            else:
                pending_before.append(context_entry)
                # Retain a bounded window so before-context can't grow unbounded.
                if len(pending_before) > 32:
                    pending_before = pending_before[-32:]
            _ = path_obj  # preserved for potential future per-file logic
            continue

        if event_type == "match":
            path_obj = (data.get("path") or {}).get("text") or ""
            line_no = data.get("line_number")
            line_text = (data.get("lines") or {}).get("text") or ""
            line_text = line_text.rstrip("\n")
            record: dict[str, Any] = {
                "path": path_obj,
                "line_number": line_no,
                "line_text": line_text,
            }
            if pending_before:
                record["before_context"] = list(pending_before)
                pending_before = []
            matches.append(record)
            last_match_index = len(matches) - 1

    return matches


async def grep_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Run a ripgrep search against the project tree and return structured results.

    See module docstring for the contract.
    """
    pattern = params.get("pattern")
    if not pattern or not isinstance(pattern, str):
        return error_output(
            message="pattern parameter is required",
            suggestion="Pass a regular expression to search for",
        )

    regex_error = _validate_regex(pattern)
    if regex_error:
        return error_output(message=regex_error, suggestion="Check your regex syntax")

    path_param = params.get("path")
    include_glob = params.get("glob")
    file_type = params.get("type")

    output_mode = params.get("output_mode", "files_with_matches")
    if output_mode not in VALID_OUTPUT_MODES:
        return error_output(
            message=f"Invalid output_mode '{output_mode}'",
            suggestion=f"output_mode must be one of: {', '.join(VALID_OUTPUT_MODES)}",
        )

    # Accept dashed JSON-style names OR python-friendly names.
    i_flag = bool(params.get("i_flag", params.get("-i", False)))
    n_flag_raw = params.get("n_flag", params.get("-n", True))
    n_flag = bool(n_flag_raw) if n_flag_raw is not None else True
    context_before = _coerce_int(params.get("B_flag", params.get("-B")))
    context_after = _coerce_int(params.get("A_flag", params.get("-A")))
    context_both = _coerce_int(params.get("C_flag", params.get("-C")))
    multiline = bool(params.get("multiline", False))

    head_limit = _coerce_int(params.get("head_limit"))
    offset = _coerce_int(params.get("offset")) or 0
    if offset < 0:
        offset = 0

    user_id = context["user_id"]
    project_id = str(context["project_id"])
    container_name = context.get("container_name")

    argv = _build_rg_args(
        pattern=pattern,
        path=path_param,
        include_glob=include_glob,
        file_type=file_type,
        output_mode=output_mode,
        i_flag=i_flag,
        n_flag=n_flag,
        context_before=context_before,
        context_after=context_after,
        context_both=context_both,
        multiline=multiline,
    )

    logger.info("[GREP] argv=%r", argv)

    try:
        orchestrator = get_orchestrator()
        raw = await orchestrator.execute_command(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            command=argv,
            timeout=60,
            working_dir=None,
        )
    except Exception as exc:
        # ``rg`` exits 1 when there are no matches; surface that as a clean
        # empty result instead of an error. Otherwise propagate.
        msg = str(exc)
        if "exit code 1" in msg.lower() or "no such file" in msg.lower():
            raw = ""
        else:
            logger.error("[GREP] execute_command failed: %s", exc)
            return error_output(
                message=f"grep failed: {exc}",
                suggestion="Ensure 'rg' (ripgrep) is installed and the project tree is accessible",
            )

    truncated_overall = False
    if len(raw.encode("utf-8", errors="replace")) > MAX_CONTENT_BYTES:
        encoded = raw.encode("utf-8", errors="replace")[:MAX_CONTENT_BYTES]
        raw = encoded.decode("utf-8", errors="replace") + "\n[truncated]"
        truncated_overall = True

    payload: dict[str, Any]

    if output_mode == "files_with_matches":
        files = _parse_files_with_matches(raw)
        sliced = files[offset : offset + head_limit] if head_limit else files[offset:]
        payload = {"files": sliced}
        msg = f"Found matches in {pluralize(len(files), 'file')}"
        if head_limit and (offset or len(sliced) < len(files)):
            msg += f" (showing {len(sliced)} of {len(files)})"
        return success_output(
            message=msg,
            details={
                "pattern": pattern,
                "output_mode": output_mode,
                "total": len(files),
                "returned": len(sliced),
                "truncated": truncated_overall,
            },
            **payload,
        )

    if output_mode == "count":
        counts = _parse_count_output(raw)
        items = list(counts.items())
        sliced_items = items[offset : offset + head_limit] if head_limit else items[offset:]
        sliced_counts = dict(sliced_items)
        total_hits = sum(counts.values())
        msg = f"{pluralize(total_hits, 'match', 'matches')} across {pluralize(len(counts), 'file')}"
        return success_output(
            message=msg,
            counts=sliced_counts,
            details={
                "pattern": pattern,
                "output_mode": output_mode,
                "total_matches": total_hits,
                "total_files": len(counts),
                "returned_files": len(sliced_counts),
                "truncated": truncated_overall,
            },
        )

    # content mode
    matches = _parse_json_output(raw)
    sliced = matches[offset : offset + head_limit] if head_limit else matches[offset:]

    msg = f"Found {pluralize(len(matches), 'match', 'matches')}"
    if head_limit and (offset or len(sliced) < len(matches)):
        msg += f" (showing {len(sliced)} of {len(matches)})"

    return success_output(
        message=msg,
        matches=sliced,
        details={
            "pattern": pattern,
            "output_mode": output_mode,
            "total": len(matches),
            "returned": len(sliced),
            "truncated": truncated_overall,
        },
    )


def register_grep_tool(registry) -> None:
    """Register the grep navigation tool."""

    registry.register(
        Tool(
            name="grep",
            description=(
                "Content search powered by ripgrep. Supports full regex, "
                "glob filters, file-type filters, context lines, count-only "
                "and files-only modes, multiline matching, and pagination via "
                "head_limit/offset."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regular expression to search for",
                    },
                    "path": {
                        "type": "string",
                        "description": "Optional subdirectory to scope the search to (relative to project root)",
                    },
                    "glob": {
                        "type": "string",
                        "description": "Glob filter to restrict which files are scanned (e.g. '*.ts', '!*.test.ts')",
                    },
                    "type": {
                        "type": "string",
                        "description": "ripgrep file-type filter (e.g. 'py', 'js', 'rust')",
                    },
                    "output_mode": {
                        "type": "string",
                        "description": (
                            "'files_with_matches' (default), 'count', or 'content'. "
                            "Use 'content' for line-level output with context."
                        ),
                    },
                    "-A": {
                        "type": "integer",
                        "description": "Lines of context after each match (content mode only)",
                    },
                    "-B": {
                        "type": "integer",
                        "description": "Lines of context before each match (content mode only)",
                    },
                    "-C": {
                        "type": "integer",
                        "description": "Lines of context on both sides of each match (content mode only)",
                    },
                    "-i": {
                        "type": "boolean",
                        "description": "Case-insensitive search (default: false)",
                    },
                    "-n": {
                        "type": "boolean",
                        "description": "Include line numbers in content mode (default: true)",
                    },
                    "multiline": {
                        "type": "boolean",
                        "description": "Allow patterns to span multiple lines (default: false)",
                    },
                    "head_limit": {
                        "type": "integer",
                        "description": "Return at most this many top-level entries (files or matches)",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Skip this many entries before applying head_limit",
                    },
                },
                "required": ["pattern"],
            },
            executor=grep_tool,
            category=ToolCategory.NAV_OPS,
            examples=[
                '{"tool_name": "grep", "parameters": {"pattern": "TODO"}}',
                '{"tool_name": "grep", "parameters": {"pattern": "def \\\\w+_tool", "output_mode": "content", "-n": true, "-C": 2}}',
                '{"tool_name": "grep", "parameters": {"pattern": "import react", "-i": true, "glob": "*.tsx", "output_mode": "count"}}',
            ],
        )
    )
