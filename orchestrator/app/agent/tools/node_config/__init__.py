"""Node-configuration agent tools.

Exposes three tools:

  * ``request_node_config`` — creates (or edits) a Container node on the
    Architecture canvas. Card lands in the user's persistent Config tab.
    Optionally pauses the agent until the user submits values.

  * ``get_project_config`` — read-only listing of every configured service /
    internal container / deployment provider in the project, with env-var
    key names. Use to check what already exists before adding a new node.

  * ``run_with_secrets`` — runs a shell command with a named subset of the
    project's encrypted secrets injected as env vars, scrubbing any secret
    substring from the returned output.
"""

from .get_project_config import register_get_project_config_tool
from .request_node_config import register_node_config_tool
from .run_with_secrets import register_run_with_secrets_tool


def register_all_node_config_tools(registry) -> None:
    register_node_config_tool(registry)
    register_get_project_config_tool(registry)
    register_run_with_secrets_tool(registry)


__all__ = [
    "register_all_node_config_tools",
    "register_get_project_config_tool",
    "register_node_config_tool",
    "register_run_with_secrets_tool",
]
