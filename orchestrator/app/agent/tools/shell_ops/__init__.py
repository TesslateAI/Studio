"""
Shell Operations Module

Essential shell execution tools for AI agents.
Supports both one-off commands (bash_exec) and persistent sessions (shell_open/exec/close).
"""

from .bash import register_bash_tools
from .execute import register_execute_tools
from .session import register_session_tools
from .upgrades import register_shell_ops_upgrades


def register_all_shell_tools(registry):
    """Register essential shell operation tools."""
    register_bash_tools(registry)  # bash_exec (PTY upgraded for local mode)
    register_session_tools(registry)  # shell_open, shell_close
    register_execute_tools(registry)  # shell_exec
    register_shell_ops_upgrades(registry)  # write_stdin, background process tools, python_repl


__all__ = [
    "register_all_shell_tools",
    "register_session_tools",
    "register_execute_tools",
    "register_bash_tools",
    "register_shell_ops_upgrades",
]
