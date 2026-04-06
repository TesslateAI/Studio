"""
Project Operations Module

Tools for accessing project metadata, controlling container lifecycle,
and managing the kanban board.
"""

from .kanban import register_kanban_tools
from .metadata import register_project_tools
from .project_control import register_project_control_tools


def register_all_project_tools(registry):
    """Register project operation tools (3 tools)."""
    register_project_tools(registry)  # get_project_info
    register_project_control_tools(registry)  # project_control
    register_kanban_tools(registry)  # kanban


__all__ = [
    "register_all_project_tools",
    "register_kanban_tools",
    "register_project_tools",
    "register_project_control_tools",
]
