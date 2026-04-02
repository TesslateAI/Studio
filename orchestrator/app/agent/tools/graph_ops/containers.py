"""
Container control tools for graph view.

These tools allow the agent to start, stop, and check status of containers
when the user is viewing the graph/architecture canvas.
"""

import logging
from typing import Any
from uuid import UUID

from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


async def graph_start_container_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """
    Start a specific container by ID.

    Args:
        params: {"container_id": "uuid-string"}
        context: Execution context with db, user_id, project_id, etc.

    Returns:
        Success/error output with container URL
    """
    container_id = params.get("container_id")
    if not container_id:
        return error_output(
            message="container_id is required",
            suggestion="Provide the UUID of the container to start",
        )

    try:
        container_uuid = UUID(container_id)
    except ValueError:
        return error_output(
            message=f"Invalid container_id format: {container_id}",
            suggestion="Provide a valid UUID",
        )

    db = context.get("db")
    user_id = context.get("user_id")
    project_id = context.get("project_id")

    if not db or not user_id or not project_id:
        return error_output(
            message="Missing required context",
            suggestion="Ensure db, user_id, and project_id are in context",
        )

    try:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from ....models import Container, ContainerConnection, Project
        from ....services.orchestration import get_orchestrator

        # Fetch container with its base relationship
        container_result = await db.execute(
            select(Container)
            .where(Container.id == container_uuid)
            .where(Container.project_id == project_id)
            .options(selectinload(Container.base))
        )
        container = container_result.scalar_one_or_none()

        if not container:
            return error_output(
                message=f"Container {container_id} not found",
                suggestion="Check the container_id is correct",
            )

        # Fetch project
        project_result = await db.execute(select(Project).where(Project.id == project_id))
        project = project_result.scalar_one_or_none()

        if not project:
            return error_output(
                message="Project not found", suggestion="Ensure you're in a valid project context"
            )

        if project.environment_status == "provisioning":
            return error_output(
                message="Project is still being provisioned. Wait for setup to complete before starting containers.",
                suggestion="Try again in a moment.",
            )

        # Fetch all containers and connections (needed for orchestrator)
        all_containers_result = await db.execute(
            select(Container)
            .where(Container.project_id == project_id)
            .options(selectinload(Container.base))
        )
        all_containers = all_containers_result.scalars().all()

        connections_result = await db.execute(
            select(ContainerConnection).where(ContainerConnection.project_id == project_id)
        )
        connections = connections_result.scalars().all()

        # Start the container
        orchestrator = get_orchestrator()
        result = await orchestrator.start_container(
            project=project,
            container=container,
            all_containers=all_containers,
            connections=connections,
            user_id=user_id,
            db=db,
        )

        return success_output(
            message=f"Container '{container.name}' started successfully",
            container_id=str(container.id),
            container_name=container.name,
            url=result.get("url"),
            status="starting",
        )

    except Exception as e:
        logger.error(f"Failed to start container: {e}", exc_info=True)
        return error_output(
            message=f"Failed to start container: {str(e)}",
            suggestion="Check container configuration and try again",
        )


async def graph_stop_container_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """
    Stop a specific container by ID.

    Args:
        params: {"container_id": "uuid-string"}
        context: Execution context

    Returns:
        Success/error output
    """
    container_id = params.get("container_id")
    if not container_id:
        return error_output(
            message="container_id is required",
            suggestion="Provide the UUID of the container to stop",
        )

    try:
        container_uuid = UUID(container_id)
    except ValueError:
        return error_output(
            message=f"Invalid container_id format: {container_id}",
            suggestion="Provide a valid UUID",
        )

    db = context.get("db")
    user_id = context.get("user_id")
    project_id = context.get("project_id")
    project_slug = context.get("project_slug")

    if not db or not user_id or not project_id:
        return error_output(
            message="Missing required context",
            suggestion="Ensure db, user_id, and project_id are in context",
        )

    try:
        from sqlalchemy import select

        from ....models import Container
        from ....services.orchestration import get_orchestrator, is_kubernetes_mode

        # Fetch container
        container_result = await db.execute(
            select(Container)
            .where(Container.id == container_uuid)
            .where(Container.project_id == project_id)
        )
        container = container_result.scalar_one_or_none()

        if not container:
            return error_output(
                message=f"Container {container_id} not found",
                suggestion="Check the container_id is correct",
            )

        # Stop the container
        from .shell import _resolve_k8s_container_name

        orchestrator = get_orchestrator()
        stop_kwargs: dict = {
            "project_slug": project_slug,
            "project_id": project_id,
            "container_name": await _resolve_k8s_container_name(project_id, container),
            "user_id": user_id,
        }
        if is_kubernetes_mode() and getattr(container, "container_type", "base") == "service":
            stop_kwargs["container_type"] = "service"
            stop_kwargs["service_slug"] = container.service_slug
        await orchestrator.stop_container(**stop_kwargs)

        return success_output(
            message=f"Container '{container.name}' stopped successfully",
            container_id=str(container.id),
            container_name=container.name,
            status="stopped",
        )

    except Exception as e:
        logger.error(f"Failed to stop container: {e}", exc_info=True)
        return error_output(
            message=f"Failed to stop container: {str(e)}",
            suggestion="Check if the container is running",
        )


async def graph_start_all_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """
    Start all containers in the project.

    Args:
        params: {} (no parameters needed)
        context: Execution context

    Returns:
        Success/error output with container info
    """
    db = context.get("db")
    user_id = context.get("user_id")
    project_id = context.get("project_id")

    if not db or not user_id or not project_id:
        return error_output(
            message="Missing required context",
            suggestion="Ensure db, user_id, and project_id are in context",
        )

    try:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from ....models import Container, ContainerConnection, Project
        from ....services.orchestration import get_orchestrator

        # Fetch project
        project_result = await db.execute(select(Project).where(Project.id == project_id))
        project = project_result.scalar_one_or_none()

        if not project:
            return error_output(
                message="Project not found", suggestion="Ensure you're in a valid project context"
            )

        if project.environment_status == "provisioning":
            return error_output(
                message="Project is still being provisioned. Wait for setup to complete before starting containers.",
                suggestion="Try again in a moment.",
            )

        # Fetch all containers
        containers_result = await db.execute(
            select(Container)
            .where(Container.project_id == project_id)
            .options(selectinload(Container.base))
        )
        containers = containers_result.scalars().all()

        if not containers:
            return error_output(
                message="No containers in this project",
                suggestion="Add containers to the project first",
            )

        # Fetch connections
        connections_result = await db.execute(
            select(ContainerConnection).where(ContainerConnection.project_id == project_id)
        )
        connections = connections_result.scalars().all()

        # Start all containers
        orchestrator = get_orchestrator()
        result = await orchestrator.start_project(project, containers, connections, user_id, db)

        container_info = result.get("containers", {})
        return success_output(
            message=f"Started {len(containers)} containers",
            containers=container_info,
            network=result.get("network"),
            namespace=result.get("namespace"),
        )

    except Exception as e:
        logger.error(f"Failed to start all containers: {e}", exc_info=True)
        return error_output(
            message=f"Failed to start containers: {str(e)}",
            suggestion="Check container configurations",
        )


async def graph_stop_all_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """
    Stop all containers in the project.

    Args:
        params: {} (no parameters needed)
        context: Execution context

    Returns:
        Success/error output
    """
    user_id = context.get("user_id")
    project_id = context.get("project_id")
    project_slug = context.get("project_slug")

    if not user_id or not project_id or not project_slug:
        return error_output(
            message="Missing required context",
            suggestion="Ensure user_id, project_id, and project_slug are in context",
        )

    try:
        from ....services.orchestration import get_orchestrator

        orchestrator = get_orchestrator()
        await orchestrator.stop_project(project_slug, project_id, user_id)

        return success_output(
            message="All containers stopped successfully", project_slug=project_slug
        )

    except Exception as e:
        logger.error(f"Failed to stop all containers: {e}", exc_info=True)
        return error_output(
            message=f"Failed to stop containers: {str(e)}",
            suggestion="Try stopping containers individually",
        )


async def graph_container_status_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """
    Get status of all containers in the project.

    Args:
        params: {} (no parameters needed)
        context: Execution context

    Returns:
        Status info for all containers
    """
    logger.info(f"[graph_container_status] Called with context keys: {list(context.keys())}")

    db = context.get("db")
    user_id = context.get("user_id")
    project_id = context.get("project_id")
    project_slug = context.get("project_slug")

    logger.info(
        f"[graph_container_status] db={db is not None}, user_id={user_id}, project_id={project_id}, project_slug={project_slug}"
    )

    if not db or not user_id or not project_id:
        return error_output(
            message="Missing required context",
            suggestion="Ensure db, user_id, and project_id are in context",
        )

    try:
        from sqlalchemy import select

        from ....models import Container
        from ....services.orchestration import get_orchestrator

        # Fetch all containers
        containers_result = await db.execute(
            select(Container).where(Container.project_id == project_id)
        )
        containers = containers_result.scalars().all()

        if not containers:
            return success_output(message="No containers in this project", containers=[])

        # Get orchestrator status
        orchestrator = get_orchestrator()
        status = await orchestrator.get_project_status(project_slug, project_id)

        # Build container list with status
        container_list = []
        status_map = status.get("containers", {})
        for container in containers:
            # Match container to status entry by container_id label (source of truth)
            cid = str(container.id)
            container_status = {}
            for _dir_key, info in status_map.items():
                if info.get("container_id") == cid:
                    container_status = info
                    break

            container_list.append(
                {
                    "id": str(container.id),
                    "name": container.name,
                    "directory": container.directory,
                    "status": "running" if container_status.get("running") else "stopped",
                    "url": container_status.get("url"),
                    "port": container.effective_port,
                }
            )

        result = success_output(
            message=f"Found {len(containers)} containers",
            project_status=status.get("status", "unknown"),
            containers=container_list,
        )
        logger.info(f"[graph_container_status] Returning result: {result}")
        return result

    except Exception as e:
        logger.error(f"[graph_container_status] Failed to get container status: {e}", exc_info=True)
        return error_output(
            message=f"Failed to get container status: {str(e)}",
            suggestion="Check project configuration",
        )


# Tool definitions
CONTAINER_TOOLS: list[Tool] = [
    Tool(
        name="graph_start_container",
        description="Start a specific container in the project. Use this to launch a single container from the architecture graph.",
        category=ToolCategory.PROJECT,
        parameters={
            "type": "object",
            "properties": {
                "container_id": {"type": "string", "description": "UUID of the container to start"}
            },
            "required": ["container_id"],
        },
        executor=graph_start_container_executor,
        examples=[
            '{"tool_name": "graph_start_container", "parameters": {"container_id": "abc-123-def"}}'
        ],
    ),
    Tool(
        name="graph_stop_container",
        description="Stop a specific container in the project. Use this to stop a single running container.",
        category=ToolCategory.PROJECT,
        parameters={
            "type": "object",
            "properties": {
                "container_id": {"type": "string", "description": "UUID of the container to stop"}
            },
            "required": ["container_id"],
        },
        executor=graph_stop_container_executor,
        examples=[
            '{"tool_name": "graph_stop_container", "parameters": {"container_id": "abc-123-def"}}'
        ],
    ),
    Tool(
        name="graph_start_all",
        description="Start all containers in the project. Use this to bring up the entire architecture.",
        category=ToolCategory.PROJECT,
        parameters={"type": "object", "properties": {}, "required": []},
        executor=graph_start_all_executor,
        examples=['{"tool_name": "graph_start_all", "parameters": {}}'],
    ),
    Tool(
        name="graph_stop_all",
        description="Stop all containers in the project. Use this to shut down the entire architecture.",
        category=ToolCategory.PROJECT,
        parameters={"type": "object", "properties": {}, "required": []},
        executor=graph_stop_all_executor,
        examples=['{"tool_name": "graph_stop_all", "parameters": {}}'],
    ),
    Tool(
        name="graph_container_status",
        description="Get the status of all containers in the project, including running state and URLs.",
        category=ToolCategory.PROJECT,
        parameters={"type": "object", "properties": {}, "required": []},
        executor=graph_container_status_executor,
        examples=['{"tool_name": "graph_container_status", "parameters": {}}'],
    ),
]
