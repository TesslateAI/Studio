"""
View context enum for view-scoped agent tools.

This module defines the different UI view contexts that can have
their own set of available tools. Tools can be scoped to specific
views, making them unavailable when the user navigates to other views.
"""

from enum import Enum
from typing import Optional


class ViewContext(Enum):
    """
    Represents the current UI view context.

    Each view can have its own set of available tools. When a user
    navigates between views, the agent's available tools change accordingly.

    Views:
        GRAPH: Architecture/Graph canvas view - project-level orchestration
        BUILDER: Builder mode - container-scoped development
        TERMINAL: Terminal panel focus
        KANBAN: Kanban board view
        UNIVERSAL: Available in all views (base tools)
    """
    GRAPH = "graph"
    BUILDER = "builder"
    TERMINAL = "terminal"
    KANBAN = "kanban"
    UNIVERSAL = "universal"

    @classmethod
    def from_string(cls, value: Optional[str]) -> "ViewContext":
        """
        Convert a string to ViewContext, defaulting to BUILDER.

        Args:
            value: String representation of view context

        Returns:
            Corresponding ViewContext enum value, or BUILDER if invalid/None
        """
        if not value:
            return cls.BUILDER
        try:
            return cls(value.lower())
        except ValueError:
            return cls.BUILDER

    @classmethod
    def valid_values(cls) -> list[str]:
        """Return list of valid view context string values."""
        return [v.value for v in cls if v != cls.UNIVERSAL]
