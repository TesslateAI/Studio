"""Project-level lifecycle tools — start, stop, restart the whole project.

Mirrors the HTTP endpoints ``/containers/start-all``, ``/containers/stop-all``
and the ``orchestrator.restart_project`` path. These three tools cover the
"bring the whole stack up / down / back up" intents the agent commonly has
between applying config and iterating.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func
from sqlalchemy import update as sql_update

from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory
from ._helpers import (
    fetch_all_containers,
    fetch_connections,
    fetch_project,
    require_project_context,
)

logger = logging.getLogger(__name__)


_EMPTY_PARAMS = {"type": "object", "properties": {}, "required": []}


async def _project_start_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    ctx = require_project_context(context)
    if ctx is None:
        return error_output(
            message="Missing required context (db, user_id, or project_id)",
            suggestion="Ensure the tool is called within a valid project session",
        )
    db, user_id, project_id = ctx

    project = await fetch_project(db, project_id)
    if not project:
        return error_output(message="Project not found")

    if project.environment_status == "provisioning":
        return error_output(
            message="Project is still being provisioned",
            suggestion="Wait for setup to complete, then try again",
        )

    containers = await fetch_all_containers(db, project_id)
    if not containers:
        return error_output(
            message="No containers to start",
            suggestion="Run apply_setup_config first to create containers from .tesslate/config.json",
        )
    connections = await fetch_connections(db, project_id)

    from ....services.orchestration import get_deployment_mode, get_orchestrator

    orchestrator = get_orchestrator()
    mode = get_deployment_mode()

    try:
        result = await orchestrator.start_project(
            project, containers, connections, user_id, db
        )
    except Exception as exc:
        logger.error("project_start failed for %s: %s", project.slug, exc, exc_info=True)
        return error_output(
            message=f"Failed to start project: {exc}",
            suggestion="Check container logs and orchestrator status",
        )

    return success_output(
        message=f"Started {len(containers)} container(s)",
        container_count=len(containers),
        containers=result.get("containers", {}),
        network=result.get("network"),
        namespace=result.get("namespace"),
        deployment_mode=mode.value,
    )


async def _project_stop_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    ctx = require_project_context(context)
    if ctx is None:
        return error_output(
            message="Missing required context (db, user_id, or project_id)",
            suggestion="Ensure the tool is called within a valid project session",
        )
    db, user_id, project_id = ctx

    project = await fetch_project(db, project_id)
    if not project:
        return error_output(message="Project not found")

    from ....models import ShellSession
    from ....services.orchestration import get_deployment_mode, get_orchestrator

    # Close any active shell sessions before tearing down pods.
    await db.execute(
        sql_update(ShellSession)
        .where(ShellSession.project_id == project.id, ShellSession.status == "active")
        .values(status="closed", closed_at=func.now())
    )
    await db.commit()

    orchestrator = get_orchestrator()
    mode = get_deployment_mode()

    try:
        await orchestrator.stop_project(project.slug, project.id, user_id)
    except Exception as exc:
        logger.error("project_stop failed for %s: %s", project.slug, exc, exc_info=True)
        return error_output(
            message=f"Failed to stop project: {exc}",
            suggestion="Check orchestrator logs",
        )

    project.environment_status = "stopped"
    await db.commit()

    return success_output(
        message="All containers stopped",
        deployment_mode=mode.value,
    )


async def _project_restart_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    ctx = require_project_context(context)
    if ctx is None:
        return error_output(
            message="Missing required context (db, user_id, or project_id)",
            suggestion="Ensure the tool is called within a valid project session",
        )
    db, user_id, project_id = ctx

    project = await fetch_project(db, project_id)
    if not project:
        return error_output(message="Project not found")

    if project.environment_status == "provisioning":
        return error_output(
            message="Project is still being provisioned",
            suggestion="Wait for setup to complete, then try again",
        )

    containers = await fetch_all_containers(db, project_id)
    if not containers:
        return error_output(
            message="No containers to restart",
            suggestion="Run apply_setup_config first to create containers from .tesslate/config.json",
        )
    connections = await fetch_connections(db, project_id)

    from ....services.orchestration import get_orchestrator

    orchestrator = get_orchestrator()

    try:
        await orchestrator.restart_project(project, containers, connections, user_id, db)
    except Exception as exc:
        logger.error(
            "project_restart failed for %s: %s", project.slug, exc, exc_info=True
        )
        return error_output(
            message=f"Failed to restart project: {exc}",
            suggestion="Check container logs and orchestrator status",
        )

    return success_output(
        message=f"Restarted {len(containers)} container(s)",
        container_count=len(containers),
    )


def register_project_lifecycle_tools(registry):
    """Register project_start, project_stop, project_restart."""
    registry.register(
        Tool(
            name="project_start",
            description=(
                "Start every container in the project. Docker: `compose up`; "
                "Kubernetes: create namespace and deployments. Use after apply_setup_config "
                "to bring a freshly-configured project online."
            ),
            category=ToolCategory.PROJECT,
            parameters=_EMPTY_PARAMS,
            executor=_project_start_executor,
            examples=['{"tool_name": "project_start", "parameters": {}}'],
        )
    )
    registry.register(
        Tool(
            name="project_stop",
            description=(
                "Stop every container in the project and close active shell sessions. "
                "Docker: `compose down`; Kubernetes: delete project namespace. "
                "Sets the project's environment_status to 'stopped'."
            ),
            category=ToolCategory.PROJECT,
            parameters=_EMPTY_PARAMS,
            executor=_project_stop_executor,
            examples=['{"tool_name": "project_stop", "parameters": {}}'],
        )
    )
    registry.register(
        Tool(
            name="project_restart",
            description=(
                "Restart every container in the project in one call. Equivalent to "
                "project_stop + project_start but wrapped in a single orchestrator action. "
                "Use after config or env var changes that require a full-stack restart."
            ),
            category=ToolCategory.PROJECT,
            parameters=_EMPTY_PARAMS,
            executor=_project_restart_executor,
            examples=['{"tool_name": "project_restart", "parameters": {}}'],
        )
    )
    logger.info("Registered 3 project_lifecycle tools (start/stop/restart)")
