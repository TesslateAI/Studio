"""
Project Operations Module

Tools for accessing project metadata and controlling container lifecycle.
"""

from .metadata import register_project_tools
from .project_control import register_project_control_tools


def register_all_project_tools(registry):
    """Register project operation tools (2 tools)."""
    register_project_tools(registry)  # get_project_info
    register_project_control_tools(registry)  # project_control


__all__ = [
    "register_all_project_tools",
    "register_project_tools",
    "register_project_control_tools",
]
