"""
Abstract base class for view-scoped tool providers.

Tool providers are responsible for:
1. Defining which tools are available in a specific view context
2. Providing tool instances with appropriate configurations
3. Validating that tool execution is allowed given current context
"""

from abc import ABC, abstractmethod
from typing import Any

from ..registry import Tool
from ..view_context import ViewContext


class AbstractToolProvider(ABC):
    """
    Abstract base class for view-scoped tool providers.

    Each provider is responsible for a specific view context and provides
    the tools available in that context. Providers can also customize
    tool configurations for their specific use case.

    Subclasses must implement:
        - get_view_context(): Return the ViewContext this provider serves
        - get_tools(): Return list of Tool instances for this view

    Subclasses may override:
        - get_tool_configs(): Return custom configs for tools
        - validate_context(): Add view-specific validation
        - is_tool_available(): Dynamic availability checks
    """

    @abstractmethod
    def get_view_context(self) -> ViewContext:
        """
        Return the view context this provider serves.

        Returns:
            ViewContext enum value
        """
        pass

    @abstractmethod
    def get_tools(self) -> list[Tool]:
        """
        Return list of tools available in this view context.

        Returns:
            List of Tool instances
        """
        pass

    def get_tool_configs(self) -> dict[str, dict[str, Any]]:
        """
        Return custom configurations for tools in this view.

        Override to provide view-specific descriptions, examples,
        or system prompts for tools.

        Returns:
            Dict mapping tool names to config dicts with keys:
            - description: Custom description
            - examples: Custom examples list
            - system_prompt: Custom system prompt
        """
        return {}

    def validate_context(self, context: dict[str, Any]) -> bool:
        """
        Validate that the execution context matches requirements.

        Override to add view-specific validation logic.
        For example, graph view might require project_id to be present.

        Args:
            context: Execution context dict

        Returns:
            True if context is valid, False otherwise
        """
        return True

    def is_tool_available(self, tool_name: str, context: dict[str, Any]) -> bool:
        """
        Check if a specific tool is available in current context.

        Default implementation: tool is available if it's in the provider's list.
        Override for dynamic availability checks (e.g., checking if containers exist).

        Args:
            tool_name: Name of the tool to check
            context: Execution context dict

        Returns:
            True if tool is available, False otherwise
        """
        return any(t.name == tool_name for t in self.get_tools())

    def get_unavailable_message(self, tool_name: str) -> str:
        """
        Return a message explaining why a tool is unavailable.

        Override to provide more specific messages.

        Args:
            tool_name: Name of the unavailable tool

        Returns:
            Human-readable explanation
        """
        return f"Tool '{tool_name}' is not available in {self.get_view_context().value} view"

    def get_tool_names(self) -> list[str]:
        """
        Get list of tool names provided by this provider.

        Returns:
            List of tool name strings
        """
        return [t.name for t in self.get_tools()]
