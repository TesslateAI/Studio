"""
File Operations Module

Essential file operation tools for AI agents.
Use shell commands (bash_exec) for listing, deleting, globbing, and grepping files.
"""

from .read_write import register_read_write_tools
from .edit import register_edit_tools


def register_all_file_tools(registry):
    """Register essential file operation tools (4 tools)."""
    register_read_write_tools(registry)  # read_file, write_file
    register_edit_tools(registry)        # patch_file, multi_edit


__all__ = [
    "register_all_file_tools",
    "register_read_write_tools",
    "register_edit_tools",
]
