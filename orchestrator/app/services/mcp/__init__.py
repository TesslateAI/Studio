"""
MCP (Model Context Protocol) integration for Tesslate Studio.

Provides multi-transport client connections (stdio, streamable-http, SSE),
tool/resource/prompt bridging into the agent's ToolRegistry, per-user MCP
server management with Redis caching, and MCP sampling support.

All connections are stateless (per-call) — each tool invocation opens a
fresh connection, calls the tool, and tears down.  This keeps the worker
pod footprint minimal and avoids long-lived subprocess management.
"""

from .bridge import bridge_mcp_prompts, bridge_mcp_resources, bridge_mcp_tools
from .client import connect_mcp
from .manager import McpManager, get_mcp_manager
from .sampling import McpSamplingHandler
from .security import build_safe_env, sanitize_error

__all__ = [
    "connect_mcp",
    "bridge_mcp_tools",
    "bridge_mcp_resources",
    "bridge_mcp_prompts",
    "McpManager",
    "get_mcp_manager",
    "McpSamplingHandler",
    "build_safe_env",
    "sanitize_error",
]
