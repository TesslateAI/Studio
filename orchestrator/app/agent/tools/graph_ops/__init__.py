"""
Graph view specific tools package.

This package contains tools that are only available when the user is
viewing the graph/architecture canvas. These tools enable agents to:
- Start/stop containers
- Add items to the grid
- Create connections between containers
- Execute commands in specific containers
"""

from typing import List
from ..registry import Tool, ToolRegistry

from .containers import CONTAINER_TOOLS
from .grid import GRID_TOOLS
from .shell import SHELL_TOOLS


def get_all_graph_tools() -> List[Tool]:
    """
    Get all graph-view-specific tools.

    Returns:
        List of Tool instances for graph view
    """
    return CONTAINER_TOOLS + GRID_TOOLS + SHELL_TOOLS


def register_all_graph_tools(registry: ToolRegistry):
    """
    Register all graph-view tools with a registry.

    Args:
        registry: ToolRegistry to register tools with
    """
    for tool in get_all_graph_tools():
        registry.register(tool)


__all__ = [
    "get_all_graph_tools",
    "register_all_graph_tools",
    "CONTAINER_TOOLS",
    "GRID_TOOLS",
    "SHELL_TOOLS",
]
