"""
Web Operations Module

Tools for fetching web content, searching the web, and sending messages.
"""

from .fetch import register_web_tools
from .search import register_search_tools
from .send_message import register_send_message_tools


def register_all_web_tools(registry):
    """Register web operation tools (3 tools)."""
    register_web_tools(registry)  # web_fetch
    register_search_tools(registry)  # web_search
    register_send_message_tools(registry)  # send_message


__all__ = [
    "register_all_web_tools",
    "register_web_tools",
    "register_search_tools",
    "register_send_message_tools",
]
