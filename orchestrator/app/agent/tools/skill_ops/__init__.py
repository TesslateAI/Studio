"""
Skill Operations Module

Tools for loading agent skills via progressive disclosure.
Only skill names and descriptions are loaded at startup;
full instructions are loaded on-demand when the agent calls load_skill.
"""

from .load_skill import register_skill_tools


def register_all_skill_tools(registry):
    """Register skill operation tools (1 tool)."""
    register_skill_tools(registry)  # load_skill


__all__ = [
    "register_all_skill_tools",
    "register_skill_tools",
]
