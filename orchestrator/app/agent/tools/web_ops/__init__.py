"""
Web Operations Module

Tools for fetching web content, searching the web, and sending messages.
"""

from .fetch import register_web_fetch_tool
from .search import register_web_search_tool
from .send_message import register_send_message_tools


def register_all_web_tools(registry):
    """Register web operation tools (3 tools)."""
    register_web_fetch_tool(registry)  # web_fetch
    register_web_search_tool(registry)  # web_search
    register_send_message_tools(registry)  # send_message


__all__ = [
    "register_all_web_tools",
    "register_web_fetch_tool",
    "register_web_search_tool",
    "register_send_message_tools",
]
