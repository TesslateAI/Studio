"""Node-configuration agent tools.

Exposes two tools:

  * ``request_node_config`` — creates (or edits) a Container node on the
    Architecture canvas, opens the config tab in the dock, and parks the
    agent until the user submits values.

  * ``run_with_secrets`` — runs a shell command with a named subset of the
    project's encrypted secrets injected as env vars, scrubbing any secret
    substring from the returned output.
"""

from .request_node_config import register_node_config_tool
from .run_with_secrets import register_run_with_secrets_tool


def register_all_node_config_tools(registry) -> None:
    register_node_config_tool(registry)
    register_run_with_secrets_tool(registry)


__all__ = [
    "register_all_node_config_tools",
    "register_node_config_tool",
    "register_run_with_secrets_tool",
]
