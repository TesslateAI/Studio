"""
Planning Operations Module

Tools for task planning and management.
Helps agents break down complex tasks and track progress.
"""

from .plan_tools import register_plan_tools
from .todos import register_planning_tools


def register_all_planning_tools(registry):
    """Register all planning operation tools."""
    register_planning_tools(registry)  # todo_read, todo_write
    register_plan_tools(registry)  # save_plan, update_plan


__all__ = [
    "register_all_planning_tools",
    "register_planning_tools",
    "register_plan_tools",
]
