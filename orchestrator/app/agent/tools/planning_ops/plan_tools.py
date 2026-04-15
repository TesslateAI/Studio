"""
Plan Tools

save_plan and update_plan tools for the Tesslate Agent's planning workflow.
These are NOT in DANGEROUS_TOOLS (safe to use in plan mode — they're how
the agent records its plan).

save_plan: Called by Plan subagent or main agent in plan mode to save a new plan
update_plan: Called by main agent during execution to track step progress
"""

import logging
from typing import Any

from ....services.plan_manager import PlanManager
from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


async def save_plan_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Save an implementation plan. Called when planning phase is complete.

    Args:
        params: {steps: [{step: str, status: str}], critical_files: [str]}
        context: Execution context with user_id and project_id
    """
    steps = params.get("steps", [])
    critical_files = params.get("critical_files", [])

    if not steps:
        return error_output(
            message="No steps provided",
            suggestion="Provide at least one step with 'step' and 'status' fields",
        )

    # Validate step format
    for i, step in enumerate(steps):
        if not step.get("step"):
            return error_output(
                message=f"Step {i + 1} is missing 'step' text",
                suggestion="Each step needs a 'step' field with a short description",
            )

    # Get task from context or use a generic description
    task = context.get("current_task", "Implementation plan")

    plan = await PlanManager.create_plan(
        context=context,
        task=task,
        steps=steps,
        critical_files=critical_files,
    )

    return success_output(
        message=f"Plan '{plan.name}' saved with {len(plan.steps)} steps",
        content=plan.to_markdown(),
        details={
            "plan_name": plan.name,
            "step_count": len(plan.steps),
            "critical_files": plan.critical_files,
        },
    )


async def update_plan_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Update the task plan. At most one step can be in_progress at a time.

    Accepts a full plan array (replaces all steps) and optional explanation.

    Args:
        params: {plan: [{step: str, status: str}], explanation?: str}
        context: Execution context
    """
    new_steps = params.get("plan", [])
    explanation = params.get("explanation", "")

    if not new_steps:
        return error_output(
            message="No plan steps provided",
            suggestion="Provide a 'plan' array with step objects",
        )

    # Validate: at most one in_progress
    in_progress = [s for s in new_steps if s.get("status") == "in_progress"]
    if len(in_progress) > 1:
        return error_output(
            message="Multiple steps marked in_progress",
            suggestion="At most one step should be in_progress at a time",
        )

    plan = await PlanManager.get_plan(context)

    if plan:
        # Update existing plan
        await PlanManager.update_plan(context, new_steps, explanation)
    else:
        # Create new plan from update_plan call
        task = context.get("current_task", "Implementation plan")
        plan = await PlanManager.create_plan(
            context=context,
            task=task,
            steps=new_steps,
            critical_files=[],
        )

    msg = f"Plan updated. {explanation}" if explanation else "Plan updated."
    return success_output(
        message=msg,
        details={
            "step_count": len(new_steps),
            "completed": sum(1 for s in new_steps if s.get("status") == "completed"),
            "in_progress": sum(1 for s in new_steps if s.get("status") == "in_progress"),
            "pending": sum(1 for s in new_steps if s.get("status") == "pending"),
        },
    )


def register_plan_tools(registry):
    """Register save_plan and update_plan tools."""
    registry.register(
        Tool(
            name="save_plan",
            description="Save the implementation plan. Call this when you have completed the planning phase.",
            parameters={
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "description": "Implementation steps (5-7 words each)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "step": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending"],
                                },
                            },
                            "required": ["step", "status"],
                        },
                    },
                    "critical_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "File paths critical for implementation (3-5 files)",
                    },
                },
                "required": ["steps", "critical_files"],
            },
            executor=save_plan_tool,
            category=ToolCategory.PROJECT,
        )
    )

    registry.register(
        Tool(
            name="update_plan",
            description=(
                "Updates the task plan. At most one step can be in_progress at a time. "
                "Do not use for simple tasks."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "explanation": {
                        "type": "string",
                        "description": "Optional explanation of plan changes",
                    },
                    "plan": {
                        "type": "array",
                        "description": "List of plan steps (5-7 words each)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "step": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                },
                            },
                            "required": ["step", "status"],
                        },
                    },
                },
                "required": ["plan"],
            },
            executor=update_plan_tool,
            category=ToolCategory.PROJECT,
        )
    )
