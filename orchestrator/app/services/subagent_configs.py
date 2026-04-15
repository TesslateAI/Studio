"""
Subagent Configurations

Provides the SubagentConfig dataclass and built-in subagent type registry.
The inline prompt templates were removed as part of the bridge cutover;
built-in subagent prompts are now served by the tesslate-agent submodule.
"""

from dataclasses import dataclass


@dataclass
class SubagentConfig:
    """Configuration for a subagent type."""

    name: str
    description: str
    tools: list[str] | None  # None = all standard tools
    system_prompt: str
    max_turns: int = 100


def _get_builtin_configs() -> dict[str, "SubagentConfig"]:
    """Return built-in subagent configurations.

    Returns an empty dict because built-in subagent prompts are now owned
    by the tesslate-agent submodule. Callers that enumerate built-ins for
    the marketplace UI will receive an empty list until those configs are
    surfaced through the bridge API.
    """
    return {}
