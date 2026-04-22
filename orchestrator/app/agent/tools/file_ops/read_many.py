"""
Read Many Files Tool

Batch-read multiple files whose paths match one or more glob patterns.
Uses the orchestrator's ``list_tree`` to enumerate candidate files (honoring
``.gitignore`` and baseline tree exclusions) and ``read_files_batch`` to
fetch contents. Applies per-file and global byte budgets so very large
files or very large match sets cannot blow up the agent context.
"""

from __future__ import annotations

import fnmatch
import logging
from pathlib import PurePosixPath
from typing import Any

from ..output_formatter import error_output, format_file_size, pluralize, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


DEFAULT_MAX_BYTES_PER_FILE = 64 * 1024  # 64 KiB
DEFAULT_MAX_TOTAL_BYTES = 1024 * 1024  # 1 MiB


# Baseline exclusions applied when ``use_default_excludes`` is true.
DEFAULT_EXCLUDE_PATTERNS: tuple[str, ...] = (
    "**/node_modules/**",
    "**/.git/**",
    "**/dist/**",
    "**/build/**",
    "**/__pycache__/**",
    "**/.venv/**",
    "**/venv/**",
    "**/.next/**",
    "**/target/**",
    "**/.mypy_cache/**",
    "**/.pytest_cache/**",
    "**/.ruff_cache/**",
    "**/.turbo/**",
    "**/.cache/**",
    "**/coverage/**",
    "**/.nyc_output/**",
    "**/out/**",
    "**/.tox/**",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.class",
    "*.o",
    "*.so",
    "*.dylib",
    "*.dll",
    "*.exe",
    "*.log",
    "*.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.zip",
    "*.tar",
    "*.tar.gz",
    "*.tgz",
    "*.rar",
    "*.7z",
)

# Binary file extensions always skipped regardless of exclude options.
BINARY_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".ico",
        ".tif",
        ".tiff",
        ".webp",
        ".svgz",
        ".pdf",
        ".mp3",
        ".mp4",
        ".wav",
        ".ogg",
        ".flac",
        ".mov",
        ".avi",
        ".mkv",
        ".webm",
        ".zip",
        ".tar",
        ".gz",
        ".tgz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".jar",
        ".war",
        ".class",
        ".pyc",
        ".pyo",
        ".so",
        ".dll",
        ".dylib",
        ".exe",
        ".bin",
        ".dat",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
    }
)


def _match_pattern(rel_path: str, pattern: str) -> bool:
    """Return True if ``rel_path`` matches glob ``pattern``."""
    normalized = rel_path.replace("\\", "/")
    if fnmatch.fnmatch(normalized, pattern):
        return True
    base = normalized.rsplit("/", 1)[-1]
    if fnmatch.fnmatch(base, pattern):
        return True
    try:
        if PurePosixPath(normalized).match(pattern):
            return True
    except (ValueError, TypeError):
        pass
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


def _matches_any(rel_path: str, patterns: list[str]) -> bool:
    """Return True if ``rel_path`` matches any glob in ``patterns``."""
    return any(_match_pattern(rel_path, pat) for pat in patterns)


def _is_binary_extension(rel_path: str) -> bool:
    """Return True if the file extension is in the binary deny-list."""
    lower = rel_path.lower()
    dot = lower.rfind(".")
    if dot == -1:
        return False
    return lower[dot:] in BINARY_EXTENSIONS


async def read_many_files_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Batch-read files matching a set of glob patterns.

    Args:
        params:
            ``include``: list of glob patterns (required, non-empty)
            ``exclude``: list of glob patterns to skip (optional)
            ``recursive``: currently informational (``**`` controls recursion)
            ``use_default_excludes``: apply the baseline exclude set (default true)
            ``file_filtering_options``: ``{respect_gitignore, respect_tesslate_ignore}``
            ``max_bytes_per_file``: per-file truncation budget
            ``max_total_bytes``: global budget (stops enumeration when exceeded)
        context: Standard tool execution context.

    Returns:
        Standard success/error dict with ``files``, ``skipped``,
        ``total_bytes`` and ``truncated_overall``.
    """
    include = params.get("include")
    if not isinstance(include, list) or not include:
        return error_output(
            message="include parameter must be a non-empty list of glob patterns",
            suggestion="Pass include=['**/*.py', 'README.md'] for example",
        )
    include = [str(p) for p in include if p]
    if not include:
        return error_output(
            message="include parameter must contain at least one non-empty pattern",
        )

    exclude_raw = params.get("exclude") or []
    if not isinstance(exclude_raw, list):
        return error_output(
            message="exclude must be a list of glob patterns if provided",
        )
    exclude = [str(p) for p in exclude_raw if p]

    use_default_excludes = bool(params.get("use_default_excludes", True))
    recursive = bool(params.get("recursive", True))
    _ = recursive  # ``**`` glob patterns drive recursion; kept for API parity

    filtering = params.get("file_filtering_options") or {}
    respect_gitignore = bool(filtering.get("respect_gitignore", True))
    respect_tesslate_ignore = bool(filtering.get("respect_tesslate_ignore", True))
    # Both flags are advisory: ``list_tree`` already honors .gitignore when the
    # backend implements it, and tesslate_ignore is applied by orchestrator
    # backends that support it.
    _ = respect_gitignore
    _ = respect_tesslate_ignore

    try:
        max_bytes_per_file = int(params.get("max_bytes_per_file", DEFAULT_MAX_BYTES_PER_FILE))
    except (TypeError, ValueError):
        max_bytes_per_file = DEFAULT_MAX_BYTES_PER_FILE
    if max_bytes_per_file < 1:
        max_bytes_per_file = DEFAULT_MAX_BYTES_PER_FILE

    try:
        max_total_bytes = int(params.get("max_total_bytes", DEFAULT_MAX_TOTAL_BYTES))
    except (TypeError, ValueError):
        max_total_bytes = DEFAULT_MAX_TOTAL_BYTES
    if max_total_bytes < 1:
        max_total_bytes = DEFAULT_MAX_TOTAL_BYTES

    effective_excludes: list[str] = []
    if use_default_excludes:
        effective_excludes.extend(DEFAULT_EXCLUDE_PATTERNS)
    effective_excludes.extend(exclude)

    user_id = context["user_id"]
    project_id = str(context["project_id"])
    container_name = context.get("container_name")
    container_directory = context.get("container_directory")

    logger.info(
        "[READ-MANY] include=%r exclude=%d defaults=%s max_per_file=%d max_total=%d",
        include,
        len(exclude),
        use_default_excludes,
        max_bytes_per_file,
        max_total_bytes,
    )

    from ....services.orchestration import get_orchestrator

    orchestrator = get_orchestrator()

    try:
        tree = await orchestrator.list_tree(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            subdir=container_directory,
        )
    except Exception as exc:
        logger.error("[READ-MANY] list_tree failed: %s", exc)
        return error_output(
            message=f"Failed to enumerate project tree: {exc}",
            suggestion="Verify the project root is accessible",
        )

    skipped: list[dict[str, str]] = []
    matched_paths: list[str] = []

    for entry in tree:
        if entry.get("is_dir"):
            continue
        rel_path = entry.get("path")
        if not rel_path:
            continue
        normalized = rel_path.replace("\\", "/")

        if _matches_any(normalized, effective_excludes):
            continue
        if not _matches_any(normalized, include):
            continue
        if _is_binary_extension(normalized):
            skipped.append({"path": normalized, "reason": "binary file extension"})
            continue

        matched_paths.append(normalized)

    matched_paths.sort()

    files_out: list[dict[str, Any]] = []
    total_bytes = 0
    truncated_overall = False

    # Batch-read in groups so a single huge batch can't stall us.
    batch_size = 32
    for start in range(0, len(matched_paths), batch_size):
        if total_bytes >= max_total_bytes:
            truncated_overall = True
            remaining = matched_paths[start:]
            for path in remaining:
                skipped.append(
                    {
                        "path": path,
                        "reason": "max_total_bytes reached before read",
                    }
                )
            break

        batch = matched_paths[start : start + batch_size]
        try:
            successes, errors = await orchestrator.read_files_batch(
                user_id=user_id,
                project_id=project_id,
                container_name=container_name,
                paths=batch,
                subdir=container_directory,
            )
        except Exception as exc:
            logger.warning("[READ-MANY] read_files_batch failed for batch: %s", exc)
            for path in batch:
                skipped.append({"path": path, "reason": f"read batch failed: {exc}"})
            continue

        for err_path in errors:
            skipped.append({"path": err_path, "reason": "read failed"})

        # Preserve sorted order by keying on path.
        by_path = {rec.get("path"): rec for rec in successes}
        for path in batch:
            rec = by_path.get(path)
            if rec is None:
                continue

            content = rec.get("content") or ""
            raw_size = int(rec.get("size") or len(content))
            file_truncated = False

            if len(content.encode("utf-8", errors="replace")) > max_bytes_per_file:
                encoded = content.encode("utf-8", errors="replace")[:max_bytes_per_file]
                content = encoded.decode("utf-8", errors="replace")
                file_truncated = True

            if total_bytes + len(content.encode("utf-8", errors="replace")) > max_total_bytes:
                remaining_budget = max(0, max_total_bytes - total_bytes)
                if remaining_budget == 0:
                    truncated_overall = True
                    skipped.append(
                        {
                            "path": path,
                            "reason": "max_total_bytes reached",
                        }
                    )
                    continue
                encoded = content.encode("utf-8", errors="replace")[:remaining_budget]
                content = encoded.decode("utf-8", errors="replace")
                file_truncated = True
                truncated_overall = True

            byte_len = len(content.encode("utf-8", errors="replace"))
            total_bytes += byte_len
            lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            if not content:
                lines = 0

            files_out.append(
                {
                    "path": path,
                    "content": content,
                    "lines": lines,
                    "size": raw_size,
                    "truncated": file_truncated,
                }
            )

            if total_bytes >= max_total_bytes:
                truncated_overall = True

    if not files_out and not skipped:
        return success_output(
            message="No files matched the provided include patterns",
            files=[],
            skipped=[],
            total_bytes=0,
            truncated_overall=False,
            details={
                "include": include,
                "exclude": exclude,
                "use_default_excludes": use_default_excludes,
            },
        )

    summary = f"Read {pluralize(len(files_out), 'file')} ({format_file_size(total_bytes)})"
    if truncated_overall:
        summary += " [truncated]"
    if skipped:
        summary += f", skipped {pluralize(len(skipped), 'file')}"

    try:
        from ....services.recent_files import get_recent_file_tracker

        tracker = get_recent_file_tracker()
        await tracker.record_many(context, [f.get("path") for f in files_out if f.get("path")])
    except Exception:
        pass

    return success_output(
        message=summary,
        files=files_out,
        skipped=skipped,
        total_bytes=total_bytes,
        truncated_overall=truncated_overall,
        details={
            "include": include,
            "exclude": exclude,
            "use_default_excludes": use_default_excludes,
            "max_bytes_per_file": max_bytes_per_file,
            "max_total_bytes": max_total_bytes,
        },
    )


def register_read_many_files_tool(registry) -> None:
    """Register the read_many_files tool."""

    registry.register(
        Tool(
            name="read_many_files",
            description=(
                "Batch-read many files at once using glob patterns. Applies "
                "per-file and total byte budgets to keep results bounded, "
                "and automatically skips binaries, lockfiles, build output, "
                "virtualenvs, and other noise unless use_default_excludes is "
                "disabled."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "include": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Glob patterns of files to include (required, non-empty)",
                    },
                    "exclude": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Glob patterns to exclude",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "Kept for API parity; recursion is controlled via '**' in patterns",
                    },
                    "use_default_excludes": {
                        "type": "boolean",
                        "description": "Apply the baseline exclude set (default: true)",
                    },
                    "file_filtering_options": {
                        "type": "object",
                        "description": "{respect_gitignore?, respect_tesslate_ignore?}",
                    },
                    "max_bytes_per_file": {
                        "type": "integer",
                        "description": f"Per-file byte budget (default: {DEFAULT_MAX_BYTES_PER_FILE})",
                    },
                    "max_total_bytes": {
                        "type": "integer",
                        "description": f"Total byte budget across all files (default: {DEFAULT_MAX_TOTAL_BYTES})",
                    },
                },
                "required": ["include"],
            },
            executor=read_many_files_tool,
            category=ToolCategory.FILE_OPS,
            examples=[
                '{"tool_name": "read_many_files", "parameters": {"include": ["**/*.py"]}}',
                '{"tool_name": "read_many_files", "parameters": {"include": ["src/**/*.ts", "src/**/*.tsx"], "exclude": ["**/*.test.ts"]}}',
                '{"tool_name": "read_many_files", "parameters": {"include": ["docs/**/*.md"], "max_bytes_per_file": 8192}}',
            ],
        )
    )
