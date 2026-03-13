"""
MCP (Model Context Protocol) integration for Tesslate Studio.

Provides client connections (stdio + Streamable HTTP), tool/resource/prompt bridging
into the agent's ToolRegistry, and per-user MCP server management with Redis caching.
"""

from .bridge import bridge_mcp_prompts, bridge_mcp_resources, bridge_mcp_tools
from .client import connect_mcp
from .manager import McpManager, get_mcp_manager

__all__ = [
    "connect_mcp",
    "bridge_mcp_tools",
    "bridge_mcp_resources",
    "bridge_mcp_prompts",
    "McpManager",
    "get_mcp_manager",
]
