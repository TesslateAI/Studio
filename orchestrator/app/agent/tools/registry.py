"""
Tool Registry System

Manages available tools for the agent and handles tool execution.
Each tool is defined with name, description, parameters schema, and executor function.
"""

from dataclasses import dataclass
from typing import Callable, Dict, Any, List, Optional
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class ToolCategory(Enum):
    """Tool categories for organization."""
    FILE_OPS = "file_operations"
    SHELL = "shell_commands"
    PROJECT = "project_management"
    BUILD = "build_operations"


@dataclass
class Tool:
    """
    Represents a tool that the agent can use.

    Attributes:
        name: Unique tool identifier
        description: What the tool does (shown to LLM)
        parameters: JSON schema for parameters
        executor: Async function that executes the tool
        category: Tool category
        examples: Example usage patterns
    """
    name: str
    description: str
    parameters: Dict[str, Any]
    executor: Callable
    category: ToolCategory
    examples: Optional[List[str]] = None

    def to_prompt_format(self) -> str:
        """Convert tool to format suitable for LLM system prompt."""
        param_descriptions = []
        for param_name, param_info in self.parameters.get("properties", {}).items():
            required = param_name in self.parameters.get("required", [])
            req_str = "required" if required else "optional"
            param_type = param_info.get("type", "string")
            desc = param_info.get("description", "")
            param_descriptions.append(f"  - {param_name} ({param_type}, {req_str}): {desc}")

        params_text = "\n".join(param_descriptions) if param_descriptions else "  No parameters"

        examples_text = ""
        if self.examples:
            examples_text = "\n  Examples:\n    " + "\n    ".join(self.examples)

        return f"""
{self.name}: {self.description}
  Parameters:
{params_text}{examples_text}
""".strip()


class ToolRegistry:
    """
    Registry of all available tools for the agent.

    Manages tool registration, lookup, and execution with proper error handling.
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        logger.info("ToolRegistry initialized")

    def register(self, tool: Tool):
        """Register a new tool."""
        if tool.name in self._tools:
            logger.warning(f"Overwriting existing tool: {tool.name}")
        self._tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name} (category: {tool.category.value})")

    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self, category: Optional[ToolCategory] = None) -> List[Tool]:
        """
        List all tools, optionally filtered by category.

        Args:
            category: Optional category filter

        Returns:
            List of Tool objects
        """
        if category:
            return [t for t in self._tools.values() if t.category == category]
        return list(self._tools.values())

    def get_system_prompt_section(self) -> str:
        """
        Generate the tools section for the system prompt.

        Returns:
            Formatted string describing all available tools
        """
        sections = []

        # Group by category
        for category in ToolCategory:
            tools = self.list_tools(category)
            if tools:
                sections.append(f"\n## {category.value.replace('_', ' ').title()}\n")
                for i, tool in enumerate(tools, 1):
                    sections.append(f"{i}. {tool.to_prompt_format()}\n")

        return "\n".join(sections)

    async def execute(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a tool with given parameters.

        Args:
            tool_name: Name of tool to execute
            parameters: Tool parameters
            context: Execution context (user_id, project_id, db session, etc.)

        Returns:
            Dict with success status and result/error
        """
        tool = self.get(tool_name)

        if not tool:
            logger.error(f"Unknown tool: {tool_name}")
            return {
                "success": False,
                "error": f"Unknown tool '{tool_name}'. Available tools: {', '.join(self._tools.keys())}"
            }

        try:
            logger.info(f"Executing tool: {tool_name} with params: {parameters}")

            # Execute the tool
            result = await tool.executor(parameters, context)

            logger.info(f"Tool {tool_name} executed successfully")
            return {
                "success": True,
                "tool": tool_name,
                "result": result
            }

        except Exception as e:
            logger.error(f"Tool {tool_name} execution failed: {e}", exc_info=True)
            return {
                "success": False,
                "tool": tool_name,
                "error": str(e)
            }


# Global registry instance
_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """Get or create the global tool registry instance."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        # Register all tools
        _register_all_tools(_registry)
    return _registry


def _register_all_tools(registry: ToolRegistry):
    """Register all available tools."""
    from . import file_tools, command_tools, project_tools, shell_tools

    # Register file operation tools
    file_tools.register_tools(registry)

    # Register command execution tools
    command_tools.register_tools(registry)

    # Register project operation tools
    project_tools.register_tools(registry)

    # Register shell operation tools
    shell_tools.register_tools(registry)

    logger.info(f"Registered {len(registry._tools)} tools total")
