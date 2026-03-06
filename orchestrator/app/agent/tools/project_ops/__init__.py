"""
Project Operations Module

Tools for accessing project metadata.
Use bash_exec for file operations and listings.
"""

from .metadata import register_project_tools


def register_all_project_tools(registry):
    """Register project operation tools (1 tool)."""
    register_project_tools(registry)  # get_project_info


__all__ = [
    "register_all_project_tools",
    "register_project_tools",
]
