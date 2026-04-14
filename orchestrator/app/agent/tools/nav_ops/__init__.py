"""
Navigation Operations Module

First-party tree / content navigation tools for the agent:
    - glob: fast pattern-based file matching with .gitignore awareness
    - grep: ripgrep-backed content search with content/count/files modes
    - list_dir: bounded-depth directory tree listing with pagination
"""

from .glob_tool import glob_tool, register_glob_tool
from .grep_tool import grep_tool, register_grep_tool
from .list_dir_tool import list_dir_tool, register_list_dir_tool


def register_nav_ops_tools(registry) -> None:
    """Register all navigation operation tools."""
    register_glob_tool(registry)
    register_grep_tool(registry)
    register_list_dir_tool(registry)


__all__ = [
    "register_nav_ops_tools",
    "register_glob_tool",
    "register_grep_tool",
    "register_list_dir_tool",
    "glob_tool",
    "grep_tool",
    "list_dir_tool",
]
