"""Container-level lifecycle tools — start, stop, restart a single container.

Mirrors the per-container HTTP endpoints. Each tool resolves the container
by name (as it appears in ``.tesslate/config.json``) rather than by UUID,
which matches how the agent refers to things elsewhere. The runs are
synchronous from the agent's point of view — it receives the final URL /
status in the tool result rather than a task_id to poll.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory
from ._helpers import (
    fetch_all_containers,
    fetch_connections,
    fetch_project,
    lookup_container_by_name,
    require_project_context,
    resolve_container_dir,
)

logger = logging.getLogger(__name__)


_CONTAINER_NAME_PARAMS = {
    "type": "object",
    "properties": {
        "container_name": {
            "type": "string",
            "description": "Name of the container as it appears in .tesslate/config.json.",
        },
    },
    "required": ["container_name"],
}


def _require_container_name(params: dict[str, Any]) -> str | None:
    name = params.get("container_name")
    if not name or not isinstance(name, str):
        return None
    return name


async def _reload_container(db, container_id):
    """Re-fetch a container with ``base`` eagerly loaded (needed by start_container)."""
    from ....models import Container

    result = await db.execute(
        select(Container)
        .where(Container.id == container_id)
        .options(selectinload(Container.base))
    )
    return result.scalar_one()


async def _container_start_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    ctx = require_project_context(context)
    if ctx is None:
        return error_output(
            message="Missing required context (db, user_id, or project_id)",
            suggestion="Ensure the tool is called within a valid project session",
        )
    db, user_id, project_id = ctx

    container_name = _require_container_name(params)
    if not container_name:
        return error_output(
            message="'container_name' is required",
            suggestion="Pass the container name from .tesslate/config.json",
        )

    project = await fetch_project(db, project_id)
    if not project:
        return error_output(message="Project not found")

    if project.environment_status == "provisioning":
        return error_output(
            message="Project is still being provisioned",
            suggestion="Wait for setup to complete, then try again",
        )

    container = await lookup_container_by_name(db, project_id, container_name)
    if not container:
        return error_output(
            message=f"Container '{container_name}' not found in this project",
            suggestion="List containers via project_control status to see valid names",
        )

    from ....config import get_settings
    from ....services.orchestration import get_orchestrator

    settings = get_settings()
    orchestrator = get_orchestrator()

    # Fast path: Docker containers that are already running just return their URL.
    if settings.deployment_mode == "docker":
        try:
            is_running = await orchestrator.is_container_running(
                project.slug, container.name
            )
        except Exception:
            is_running = False
        if is_running:
            # Mirror docker.py's sanitization of the container name when
            # building the traefik hostname — names may contain ".", "_",
            # or spaces that the router rejects.
            import re

            sanitized = (
                container.name.lower()
                .replace(" ", "-")
                .replace("_", "-")
                .replace(".", "-")
            )
            sanitized = "".join(c for c in sanitized if c.isalnum() or c == "-")
            sanitized = re.sub(r"-+", "-", sanitized).strip("-")
            url = f"http://{project.slug}-{sanitized}.{settings.app_domain}"
            return success_output(
                message=f"Container '{container_name}' already running",
                container_name=container_name,
                url=url,
                already_running=True,
            )

    # Slow path: start the container. We re-fetch with ``base`` eagerly loaded
    # (start_container relies on the relationship).
    container = await _reload_container(db, container.id)
    all_containers = await fetch_all_containers(db, project_id)
    connections = await fetch_connections(db, project_id)

    try:
        result = await orchestrator.start_container(
            project=project,
            container=container,
            all_containers=all_containers,
            connections=connections,
            user_id=user_id,
            db=db,
        )
    except Exception as exc:
        logger.error(
            "container_start failed for %s: %s", container_name, exc, exc_info=True
        )
        return error_output(
            message=f"Failed to start container: {exc}",
            suggestion="Check container logs and orchestrator status",
        )

    return success_output(
        message=f"Container '{container_name}' starting",
        container_name=container_name,
        url=result.get("url"),
        status="starting",
    )


async def _container_stop_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    ctx = require_project_context(context)
    if ctx is None:
        return error_output(
            message="Missing required context (db, user_id, or project_id)",
            suggestion="Ensure the tool is called within a valid project session",
        )
    db, user_id, project_id = ctx

    container_name = _require_container_name(params)
    if not container_name:
        return error_output(
            message="'container_name' is required",
            suggestion="Pass the container name from .tesslate/config.json",
        )

    container = await lookup_container_by_name(db, project_id, container_name)
    if not container:
        return error_output(
            message=f"Container '{container_name}' not found in this project",
            suggestion="List containers via project_control status to see valid names",
        )

    project = await fetch_project(db, project_id)
    if not project:
        return error_output(message="Project not found")

    from ....services.orchestration import get_orchestrator, is_kubernetes_mode

    orchestrator = get_orchestrator()
    dir_key = await resolve_container_dir(project_id, container)

    stop_kwargs: dict[str, Any] = {
        "project_slug": project.slug,
        "project_id": project_id,
        "container_name": dir_key,
        "user_id": user_id,
    }
    if is_kubernetes_mode() and getattr(container, "container_type", "base") == "service":
        stop_kwargs["container_type"] = "service"
        stop_kwargs["service_slug"] = container.service_slug

    try:
        await orchestrator.stop_container(**stop_kwargs)
    except Exception as exc:
        logger.error(
            "container_stop failed for %s: %s", container_name, exc, exc_info=True
        )
        return error_output(
            message=f"Failed to stop container: {exc}",
            suggestion="Check orchestrator logs",
        )

    return success_output(
        message=f"Container '{container_name}' stopped",
        container_name=container_name,
    )


async def _container_restart_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    ctx = require_project_context(context)
    if ctx is None:
        return error_output(
            message="Missing required context (db, user_id, or project_id)",
            suggestion="Ensure the tool is called within a valid project session",
        )
    db, user_id, project_id = ctx

    container_name = _require_container_name(params)
    if not container_name:
        return error_output(
            message="'container_name' is required",
            suggestion="Pass the container name from .tesslate/config.json",
        )

    project = await fetch_project(db, project_id)
    if not project:
        return error_output(message="Project not found")

    if project.environment_status == "provisioning":
        return error_output(
            message="Project is still being provisioned",
            suggestion="Wait for setup to complete, then try again",
        )

    container = await lookup_container_by_name(db, project_id, container_name)
    if not container:
        return error_output(
            message=f"Container '{container_name}' not found in this project",
            suggestion="List containers via project_control status to see valid names",
        )

    from ....services.orchestration import get_orchestrator, is_kubernetes_mode

    orchestrator = get_orchestrator()

    # --- Stop ---
    dir_key = await resolve_container_dir(project_id, container)
    stop_kwargs: dict[str, Any] = {
        "project_slug": project.slug,
        "project_id": project_id,
        "container_name": dir_key,
        "user_id": user_id,
    }
    if is_kubernetes_mode() and getattr(container, "container_type", "base") == "service":
        stop_kwargs["container_type"] = "service"
        stop_kwargs["service_slug"] = container.service_slug

    try:
        await orchestrator.stop_container(**stop_kwargs)
    except Exception as exc:
        logger.warning("stop_container failed for %s: %s", container_name, exc)
        # Proceed to start — container may already be stopped.

    # --- Start ---
    container = await _reload_container(db, container.id)
    all_containers = await fetch_all_containers(db, project_id)
    connections = await fetch_connections(db, project_id)

    try:
        result = await orchestrator.start_container(
            project=project,
            container=container,
            all_containers=all_containers,
            connections=connections,
            user_id=user_id,
            db=db,
        )
    except Exception as exc:
        logger.error(
            "container_restart failed for %s: %s", container_name, exc, exc_info=True
        )
        return error_output(
            message=f"Failed to restart container: {exc}",
            suggestion="Check container logs",
        )

    return success_output(
        message=f"Container '{container_name}' restarted",
        container_name=container_name,
        url=result.get("url"),
        status="starting",
    )


def register_container_lifecycle_tools(registry):
    """Register container_start, container_stop, container_restart."""
    registry.register(
        Tool(
            name="container_start",
            description=(
                "Start a single container by name. Fast path: in Docker mode, "
                "if the container is already running, returns its URL immediately. "
                "Otherwise invokes the orchestrator's start path (same logic as the UI)."
            ),
            category=ToolCategory.PROJECT,
            parameters=_CONTAINER_NAME_PARAMS,
            executor=_container_start_executor,
            # container_name in, status+url dict out — JSON-clean.
            state_serializable=True,
            # Mutates orchestrator state (containers) but the tool itself
            # holds no in-flight handle; success returns immediately.
            holds_external_state=False,
            examples=[
                '{"tool_name": "container_start", "parameters": {"container_name": "frontend"}}'
            ],
        )
    )
    registry.register(
        Tool(
            name="container_stop",
            description=(
                "Stop a single container by name (synchronous). Handles the K8s "
                "service-slug special case automatically."
            ),
            category=ToolCategory.PROJECT,
            parameters=_CONTAINER_NAME_PARAMS,
            executor=_container_stop_executor,
            # container_name in, success dict out — JSON-clean.
            state_serializable=True,
            # Synchronous orchestrator call; no in-tool persistent handle.
            holds_external_state=False,
            examples=[
                '{"tool_name": "container_stop", "parameters": {"container_name": "postgres"}}'
            ],
        )
    )
    registry.register(
        Tool(
            name="container_restart",
            description=(
                "Restart a single container by name (stop + start). Useful after "
                "changing env vars or startup commands without touching other containers."
            ),
            category=ToolCategory.PROJECT,
            parameters=_CONTAINER_NAME_PARAMS,
            executor=_container_restart_executor,
            # container_name in, success dict out — JSON-clean.
            state_serializable=True,
            # Synchronous orchestrator call (stop+start); no in-tool handle.
            holds_external_state=False,
            examples=[
                '{"tool_name": "container_restart", "parameters": {"container_name": "frontend"}}'
            ],
        )
    )
    logger.info("Registered 3 container_lifecycle tools (start/stop/restart)")
