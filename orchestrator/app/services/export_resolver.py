"""
Export resolver — resolves ${} interpolation in node exports.

Each node's exports reference only the node's own properties:
  ${HOST}         — the node's dict key (= hostname in Docker/K8s)
  ${PORT}         — the node's port field
  ${ANY_ENV_KEY}  — any key from the node's env dict
"""

import logging
import re

logger = logging.getLogger(__name__)

_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def resolve_node_exports(
    node_name: str,
    exports: dict[str, str],
    env: dict[str, str],
    port: int | None = None,
) -> dict[str, str]:
    """Resolve ${} placeholders in a node's exports against its own properties."""
    if not exports:
        return {}

    context: dict[str, str] = {
        "HOST": node_name,
        "PORT": str(port) if port is not None else "",
        **env,
    }

    resolved = {}
    for key, template in exports.items():
        def replacer(match: re.Match, _ctx=context, _node=node_name, _key=key) -> str:
            var = match.group(1)
            if var in _ctx:
                return _ctx[var]
            logger.warning(f"[EXPORTS] Unresolved variable ${{{var}}} in {_node}.exports.{_key}")
            return match.group(0)  # leave as-is

        resolved[key] = _VAR_PATTERN.sub(replacer, template)

    return resolved


def build_env_from_connections(
    node_name: str,
    nodes: dict[str, dict],
    connections: list[dict],
) -> dict[str, str]:
    """Build the injected env vars for a node by resolving exports from all connected targets.

    For each connection where node_name is the 'from', resolve the 'to' node's exports
    and merge them into the result.
    """
    injected: dict[str, str] = {}

    for conn in connections:
        if conn.get("from") != node_name:
            continue
        target_name = conn.get("to", "")
        target = nodes.get(target_name)
        if not target:
            logger.warning(f"[EXPORTS] Connection target '{target_name}' not found")
            continue

        resolved = resolve_node_exports(
            node_name=target_name,
            exports=target.get("exports", {}),
            env=target.get("env", {}),
            port=target.get("port"),
        )
        injected.update(resolved)

    return injected
