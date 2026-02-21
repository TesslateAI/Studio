"""
Tool Converter

Converts Tesslate's Tool dataclass (from tools/registry.py) to OpenAI function calling format.
This bridges the gap between Tesslate's internal tool representation and the OpenAI API's
native function calling interface used by TesslateAgent.
"""

import logging
from typing import Any

from .tools.registry import Tool, ToolRegistry

logger = logging.getLogger(__name__)

# Tools that are safe to execute in parallel (read-only or idempotent, no side effects)
PARALLEL_TOOLS = frozenset(
    {
        "read_file",
        "get_project_info",
        "todo_read",
        "web_fetch",
        "grep_files",
        "list_dir",
        "save_plan",
        "update_plan",
    }
)


def is_parallel_tool(name: str) -> bool:
    """Check if a tool can be safely executed in parallel with other tools."""
    return name in PARALLEL_TOOLS


def tool_to_openai_format(tool: Tool) -> dict[str, Any]:
    """
    Convert a Tesslate Tool dataclass to OpenAI function calling format.

    Args:
        tool: Tesslate Tool instance

    Returns:
        Dict in OpenAI function calling format:
        {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
    """
    function_def: dict[str, Any] = {
        "name": tool.name,
        "description": tool.description,
    }

    # Include parameters schema if present
    if tool.parameters:
        function_def["parameters"] = tool.parameters
    else:
        # OpenAI requires a parameters object even if empty
        function_def["parameters"] = {"type": "object", "properties": {}}

    return {
        "type": "function",
        "function": function_def,
    }


def registry_to_openai_tools(registry: ToolRegistry) -> list[dict[str, Any]]:
    """
    Convert an entire ToolRegistry to OpenAI tools array.

    Args:
        registry: Tesslate ToolRegistry instance

    Returns:
        List of tool definitions in OpenAI function calling format
    """
    tools = []
    for tool in registry.list_tools():
        openai_tool = tool_to_openai_format(tool)
        tools.append(openai_tool)

    logger.debug(f"Converted {len(tools)} tools to OpenAI format")
    return tools
