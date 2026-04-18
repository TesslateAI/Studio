"""
Project Operations Module

Tools for observing project state, mutating the project config graph,
controlling container lifecycle, and managing the kanban board.

Layout:
  * ``metadata``             — get_project_info
  * ``project_control``      — status, container_logs, health_check (observation only)
  * ``setup_config``         — apply_setup_config (write config.json + sync graph)
  * ``project_lifecycle``    — project_start, project_stop, project_restart
  * ``container_lifecycle``  — container_start, container_stop, container_restart
  * ``kanban``               — kanban board management
"""

from .container_lifecycle import register_container_lifecycle_tools
from .kanban import register_kanban_tools
from .metadata import register_project_tools
from .project_control import register_project_control_tools
from .project_lifecycle import register_project_lifecycle_tools
from .setup_config import register_setup_config_tool


def register_all_project_tools(registry):
    """Register every project_ops tool."""
    register_project_tools(registry)  # get_project_info
    register_project_control_tools(registry)  # project_control (observation)
    register_setup_config_tool(registry)  # apply_setup_config
    register_project_lifecycle_tools(registry)  # project_start/stop/restart
    register_container_lifecycle_tools(registry)  # container_start/stop/restart
    register_kanban_tools(registry)  # kanban


__all__ = [
    "register_all_project_tools",
    "register_container_lifecycle_tools",
    "register_kanban_tools",
    "register_project_control_tools",
    "register_project_lifecycle_tools",
    "register_project_tools",
    "register_setup_config_tool",
]
