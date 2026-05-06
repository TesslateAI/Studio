"""Workspace-attachment agent tools.

Exposes ``request_workspace`` — the agent-side companion to the chat's
"+ Connect a workspace" affordance. When a standalone chat (no
``project_id``) needs storage / compute / persistence, the agent calls
this tool, the user picks an existing workspace or creates an empty one,
and ``Chat.project_id`` is set in place. Every existing file tool
(``read_file``, ``write_file``, ``grep``, ``view_image``) then resolves
against the new workspace with zero further plumbing.
"""

from .request_workspace import register_workspace_tool


def register_all_workspace_tools(registry) -> None:
    register_workspace_tool(registry)


__all__ = [
    "register_all_workspace_tools",
    "register_workspace_tool",
]
