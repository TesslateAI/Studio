"""
App Operations Module

Tools for invoking typed actions on installed Tesslate Apps. This is the
first cross-app primitive — agents can compose installed apps without
leaving the chat.

Phase 1 of the OpenSail Automation Runtime — see
``/Users/smirk/.claude/plans/ultrathink-i-want-to-glittery-pond.md``
§"App actions" + §"invoke_app_action".
"""

from .invoke_app_action import register_invoke_app_action_tool


def register_all_app_ops_tools(registry):
    """Register app operation tools (1 tool)."""
    register_invoke_app_action_tool(registry)  # invoke_app_action


__all__ = [
    "register_all_app_ops_tools",
    "register_invoke_app_action_tool",
]
