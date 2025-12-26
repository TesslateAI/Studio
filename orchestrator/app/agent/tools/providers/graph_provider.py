"""
Graph view tool provider.

Provides tools specific to the graph/architecture canvas view.
These tools are only available when the user is viewing the graph.
"""

import logging
from typing import List, Dict, Any

from .base import AbstractToolProvider
from ..view_context import ViewContext
from ..registry import Tool
from ..graph_ops import get_all_graph_tools

logger = logging.getLogger(__name__)


class GraphToolProvider(AbstractToolProvider):
    """
    Provides tools for the graph/architecture view.

    Tools provided:
    - Container control: start, stop, status
    - Grid management: add containers, connections, browser previews
    - Shell access: connect to specific containers
    """

    def get_view_context(self) -> ViewContext:
        """Return GRAPH view context."""
        return ViewContext.GRAPH

    def get_tools(self) -> List[Tool]:
        """Return all graph-specific tools."""
        return get_all_graph_tools()

    def get_tool_configs(self) -> Dict[str, Dict[str, Any]]:
        """
        Return custom configurations for graph tools.

        These configs can override default descriptions for
        better context in graph view.
        """
        return {
            "graph_start_container": {
                "system_prompt": "Use this to start a container you see on the graph. You can get the container_id from graph_container_status."
            },
            "graph_stop_container": {
                "system_prompt": "Use this to stop a running container on the graph."
            },
            "graph_container_status": {
                "system_prompt": "Call this first to see all containers and their IDs before performing operations."
            }
        }

    def validate_context(self, context: Dict[str, Any]) -> bool:
        """
        Validate that we have project context for graph operations.

        Graph tools require:
        - project_id: UUID of the project
        - db: Database session
        """
        return (
            context.get("project_id") is not None and
            context.get("db") is not None
        )

    def is_tool_available(
        self,
        tool_name: str,
        context: Dict[str, Any]
    ) -> bool:
        """
        Check if a specific tool is available.

        All graph tools are available if the context is valid.
        """
        if not self.validate_context(context):
            return False
        return super().is_tool_available(tool_name, context)

    def get_unavailable_message(self, tool_name: str) -> str:
        """Return explanation for unavailable tools."""
        return (
            f"Tool '{tool_name}' is only available in graph view. "
            f"Switch to the architecture/graph canvas to use container management tools."
        )
