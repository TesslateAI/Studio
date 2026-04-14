"""
Shell-Ops Upgrade Registration

Central entry point for the upgraded shell tooling (``write_stdin``,
background-process inspectors, and the persistent Python REPL). The
existing ``bash_exec`` registration is performed by
``shell_ops/bash.py``; this module only layers the new tools on top.

Call :func:`register_shell_ops_upgrades` from the top-level tool wiring
after the base shell tools have been registered.
"""

from __future__ import annotations

import logging

from .background import register_background_tools
from .python_repl import register_python_repl_tool
from .write_stdin import register_write_stdin_tool

logger = logging.getLogger(__name__)


def register_shell_ops_upgrades(registry) -> None:
    """
    Register the upgraded shell-ops tools on ``registry``.

    Adds four tools:

    - ``write_stdin``
    - ``list_background_processes``
    - ``read_background_output``
    - ``python_repl``
    """
    register_write_stdin_tool(registry)
    register_background_tools(registry)
    register_python_repl_tool(registry)
    logger.info("Registered shell-ops upgrades (4 tools)")


__all__ = ["register_shell_ops_upgrades"]
