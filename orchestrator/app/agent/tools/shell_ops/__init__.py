"""
Shell Operations Module

Essential shell execution tools for AI agents.
Supports both one-off commands (bash_exec) and persistent sessions (shell_open/exec/close).
"""

from .session import register_session_tools
from .execute import register_execute_tools
from .bash import register_bash_tools


def register_all_shell_tools(registry):
    """Register essential shell operation tools (4 tools)."""
    register_bash_tools(registry)        # bash_exec
    register_session_tools(registry)     # shell_open, shell_close
    register_execute_tools(registry)     # shell_exec


__all__ = [
    "register_all_shell_tools",
    "register_session_tools",
    "register_execute_tools",
    "register_bash_tools",
]
