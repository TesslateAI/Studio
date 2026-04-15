"""Async git-diff helper used by desktop endpoints and the handoff client.

Returns the combined staged + unstaged ``git diff HEAD`` output for a
project's working tree. Never raises — all failure modes (missing git
binary, missing .git dir, subprocess timeout) collapse to an empty string
so callers stay non-blocking.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from .orchestration.local import _get_project_root

logger = logging.getLogger(__name__)

DIFF_TIMEOUT_SECONDS = 5.0
DIFF_MAX_BYTES = 1_000_000


async def git_diff_for_project(project: Any) -> str:
    try:
        root = Path(str(project.source_path)) if project.source_path else _get_project_root(project)
    except Exception:
        return ""
    if not root or not root.is_dir() or not (root / ".git").exists():
        return ""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(root),
            "diff",
            "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=DIFF_TIMEOUT_SECONDS)
    except (TimeoutError, FileNotFoundError, OSError) as exc:
        logger.debug("git diff for %s failed: %s", root, exc)
        return ""
    text = stdout.decode("utf-8", errors="replace")
    if len(text) > DIFF_MAX_BYTES:
        text = text[:DIFF_MAX_BYTES] + "\n... (diff truncated)\n"
    return text
