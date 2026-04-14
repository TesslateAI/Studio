"""
Git Operations Module

First-party agent tools for inspecting git repositories inside a project.
All tools execute the standard ``git`` CLI via the active orchestrator's
``execute_command`` backend and parse the machine-readable output into
structured dicts suitable for LLM consumption.

Tools:
    - git_log: commit history with structured per-commit fields
    - git_blame: line-porcelain blame for a file or range
    - git_status: porcelain v2 status with branch and stash info
    - git_diff: parsed unified diff between working tree / index / refs

All tools are read-only and therefore carry no scope requirement in
``ToolRegistry.TOOL_REQUIRED_SCOPES``.
"""

from .git_blame_tool import register_git_blame_tool
from .git_diff_tool import register_git_diff_tool
from .git_log_tool import register_git_log_tool
from .git_status_tool import register_git_status_tool


def register_git_ops_tools(registry) -> None:
    """Register all git inspection tools with the provided registry."""
    register_git_log_tool(registry)
    register_git_blame_tool(registry)
    register_git_status_tool(registry)
    register_git_diff_tool(registry)


__all__ = [
    "register_git_ops_tools",
    "register_git_log_tool",
    "register_git_blame_tool",
    "register_git_status_tool",
    "register_git_diff_tool",
]
