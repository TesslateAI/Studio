"""
Web Operations Module

Tools for fetching web content.
Useful for agents that need external documentation or API responses.
"""

from .fetch import register_web_tools


def register_all_web_tools(registry):
    """Register web operation tools (1 tool)."""
    register_web_tools(registry)  # web_fetch


__all__ = [
    "register_all_web_tools",
    "register_web_tools",
]
