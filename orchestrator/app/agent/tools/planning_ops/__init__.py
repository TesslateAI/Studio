"""
Planning Operations Module

Tools for task planning and management.
Helps agents break down complex tasks and track progress.
"""

from .plan_tools import register_plan_tools
from .todos import register_planning_tools
from .update_plan import PLAN_STORE, PlanStore, register_update_plan_tool


def register_all_planning_tools(registry):
    """Register all planning operation tools."""
    register_planning_tools(registry)  # todo_read, todo_write
    register_plan_tools(registry)  # save_plan, legacy update_plan
    register_update_plan_tool(registry)  # structured update_plan (replaces legacy)


__all__ = [
    "register_all_planning_tools",
    "register_planning_tools",
    "register_plan_tools",
    "register_update_plan_tool",
    "PLAN_STORE",
    "PlanStore",
]
