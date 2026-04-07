"""
Agent Schedule Management Tool

Allows agents to create, list, update, pause, resume, trigger, and delete
cron-scheduled agent tasks directly from within an agent conversation.
"""

import logging
from typing import Any
from uuid import UUID

from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


async def manage_schedule_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """
    Manage agent schedules (cron-scheduled tasks).

    Args:
        params: {
            action: "create" | "list" | "update" | "pause" | "resume" | "trigger" | "delete",
            name: str (for create/update),
            schedule: str (natural language or cron, for create/update),
            prompt: str (for create/update),
            deliver: str (for create, default "origin"),
            job_id: str (UUID, for update/pause/resume/trigger/delete),
        }
        context: Execution context with user_id, project_id, db.
    """
    action = params.get("action")
    if not action:
        return error_output(message="action parameter is required")

    db = context.get("db")
    if not db:
        return error_output(message="Database session not available")

    user_id = context.get("user_id")
    project_id = context.get("project_id")

    if action == "create":
        return await _create(params, db, user_id, project_id)
    elif action == "list":
        return await _list(db, user_id, project_id)
    elif action == "update":
        return await _update(params, db, user_id)
    elif action == "pause":
        return await _pause(params, db, user_id)
    elif action == "resume":
        return await _resume(params, db, user_id)
    elif action == "trigger":
        return await _trigger(params, db, user_id, project_id, context)
    elif action == "delete":
        return await _delete(params, db, user_id)
    else:
        return error_output(
            message=f"Unknown action '{action}'",
            suggestion="Use: create, list, update, pause, resume, trigger, delete",
        )


async def _create(params, db, user_id, project_id):
    from sqlalchemy import func, select

    from ....config import get_settings
    from ....models import AgentSchedule
    from ....services.gateway.schedule_parser import parse_schedule
    from ....services.gateway.scheduler import compute_next_run

    settings = get_settings()
    name = params.get("name")
    schedule_expr = params.get("schedule")
    prompt = params.get("prompt")

    if not name or not schedule_expr or not prompt:
        return error_output(message="name, schedule, and prompt are required for create")

    if not project_id:
        return error_output(message="No project context — schedule requires a project")

    # Check limit
    count = await db.scalar(
        select(func.count())
        .select_from(AgentSchedule)
        .where(AgentSchedule.user_id == user_id, AgentSchedule.is_active.is_(True))
    )
    if count and count >= settings.gateway_max_schedules_per_user:
        return error_output(
            message=f"Limit of {settings.gateway_max_schedules_per_user} active schedules reached"
        )

    try:
        normalized = parse_schedule(schedule_expr)
    except ValueError as e:
        return error_output(message=str(e))

    schedule = AgentSchedule(
        user_id=user_id,
        project_id=project_id,
        name=name,
        cron_expression=schedule_expr,
        normalized_cron=normalized,
        prompt_template=prompt,
        deliver=params.get("deliver", "origin"),
        next_run_at=compute_next_run(normalized),
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)

    return success_output(
        message=f"Schedule '{name}' created",
        job_id=str(schedule.id),
        cron=normalized,
        next_run=str(schedule.next_run_at),
    )


async def _list(db, user_id, project_id):
    from sqlalchemy import select

    from ....models import AgentSchedule

    query = select(AgentSchedule).where(AgentSchedule.user_id == user_id)
    if project_id:
        query = query.where(AgentSchedule.project_id == project_id)
    query = query.order_by(AgentSchedule.created_at.desc()).limit(20)

    result = await db.execute(query)
    schedules = result.scalars().all()

    items = [
        {
            "id": str(s.id),
            "name": s.name,
            "cron": s.normalized_cron,
            "active": s.is_active,
            "next_run": str(s.next_run_at) if s.next_run_at else None,
            "runs": s.runs_completed,
            "last_status": s.last_status,
        }
        for s in schedules
    ]
    return success_output(message=f"Found {len(items)} schedule(s)", schedules=items)


async def _update(params, db, user_id):
    from sqlalchemy import select

    from ....models import AgentSchedule
    from ....services.gateway.schedule_parser import parse_schedule
    from ....services.gateway.scheduler import compute_next_run

    job_id = params.get("job_id")
    if not job_id:
        return error_output(message="job_id is required for update")

    result = await db.execute(
        select(AgentSchedule).where(
            AgentSchedule.id == UUID(job_id),
            AgentSchedule.user_id == user_id,
        )
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        return error_output(message="Schedule not found")

    if params.get("name"):
        schedule.name = params["name"]
    if params.get("prompt"):
        schedule.prompt_template = params["prompt"]
    if params.get("deliver"):
        schedule.deliver = params["deliver"]

    if params.get("schedule"):
        try:
            normalized = parse_schedule(params["schedule"])
        except ValueError as e:
            return error_output(message=str(e))
        schedule.cron_expression = params["schedule"]
        schedule.normalized_cron = normalized
        schedule.next_run_at = compute_next_run(normalized)

    await db.commit()
    return success_output(message=f"Schedule '{schedule.name}' updated")


async def _pause(params, db, user_id):
    from sqlalchemy import select

    from ....models import AgentSchedule

    job_id = params.get("job_id")
    if not job_id:
        return error_output(message="job_id is required")

    result = await db.execute(
        select(AgentSchedule).where(
            AgentSchedule.id == UUID(job_id),
            AgentSchedule.user_id == user_id,
        )
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        return error_output(message="Schedule not found")

    schedule.is_active = False
    await db.commit()
    return success_output(message=f"Schedule '{schedule.name}' paused")


async def _resume(params, db, user_id):
    from sqlalchemy import select

    from ....models import AgentSchedule
    from ....services.gateway.scheduler import compute_next_run

    job_id = params.get("job_id")
    if not job_id:
        return error_output(message="job_id is required")

    result = await db.execute(
        select(AgentSchedule).where(
            AgentSchedule.id == UUID(job_id),
            AgentSchedule.user_id == user_id,
        )
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        return error_output(message="Schedule not found")

    schedule.is_active = True
    schedule.next_run_at = compute_next_run(schedule.normalized_cron)
    await db.commit()
    return success_output(
        message=f"Schedule '{schedule.name}' resumed",
        next_run=str(schedule.next_run_at),
    )


async def _trigger(params, db, user_id, project_id, context):
    from sqlalchemy import select

    from ....models import AgentSchedule

    job_id = params.get("job_id")
    if not job_id:
        return error_output(message="job_id is required")

    result = await db.execute(
        select(AgentSchedule).where(
            AgentSchedule.id == UUID(job_id),
            AgentSchedule.user_id == user_id,
        )
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        return error_output(message="Schedule not found")

    return success_output(
        message=f"Schedule '{schedule.name}' trigger requested. "
        "Use the Schedules API POST /api/schedules/{id}/trigger for immediate execution.",
    )


async def _delete(params, db, user_id):
    from sqlalchemy import select

    from ....models import AgentSchedule

    job_id = params.get("job_id")
    if not job_id:
        return error_output(message="job_id is required")

    result = await db.execute(
        select(AgentSchedule).where(
            AgentSchedule.id == UUID(job_id),
            AgentSchedule.user_id == user_id,
        )
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        return error_output(message="Schedule not found")

    await db.delete(schedule)
    await db.commit()
    return success_output(message=f"Schedule '{schedule.name}' deleted")


def register_schedule_tools(registry):
    """Register manage_schedule tool."""
    registry.register(
        Tool(
            name="manage_schedule",
            description=(
                "Create, list, update, pause, resume, trigger, or delete cron-scheduled "
                "agent tasks. Schedules run automatically and can deliver results to any "
                "connected messaging platform."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action to perform",
                        "enum": [
                            "create",
                            "list",
                            "update",
                            "pause",
                            "resume",
                            "trigger",
                            "delete",
                        ],
                    },
                    "name": {
                        "type": "string",
                        "description": "Schedule name (for create/update)",
                    },
                    "schedule": {
                        "type": "string",
                        "description": "Schedule expression: natural language ('daily at 9am', 'every 30m') or 5-field cron",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Prompt template for the scheduled task. Supports {date}, {time}, {weekday} variables.",
                    },
                    "deliver": {
                        "type": "string",
                        "description": "Delivery target: 'origin' (default), platform name, or platform:chat_id",
                        "default": "origin",
                    },
                    "job_id": {
                        "type": "string",
                        "description": "Schedule UUID (for update/pause/resume/trigger/delete)",
                    },
                },
                "required": ["action"],
            },
            executor=manage_schedule_executor,
            category=ToolCategory.WEB,
            examples=[
                '{"tool_name": "manage_schedule", "parameters": {"action": "create", "name": "Daily report", "schedule": "daily at 9am", "prompt": "Generate a summary of project activity for {date}"}}',
                '{"tool_name": "manage_schedule", "parameters": {"action": "list"}}',
            ],
        )
    )
    logger.info("Registered 1 manage_schedule tool")
