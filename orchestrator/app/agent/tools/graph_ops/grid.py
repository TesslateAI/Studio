"""
Grid management tools for graph view.

These tools allow the agent to add containers, browser previews,
and connections to the architecture graph canvas.
"""

import logging
from typing import Any
from uuid import UUID, uuid4

from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


async def graph_add_container_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """
    Add a new container to the architecture grid.

    Args:
        params: {
            "name": "container-name",
            "base_id": "optional-marketplace-base-uuid",
            "container_type": "base" | "service",
            "service_slug": "postgres" (if container_type is service),
            "position_x": 100,
            "position_y": 200,
            "port": 3000
        }
        context: Execution context

    Returns:
        Success/error output with container info
    """
    name = params.get("name")
    if not name:
        return error_output(
            message="name is required", suggestion="Provide a name for the container"
        )

    db = context.get("db")
    project_id = context.get("project_id")
    project_slug = context.get("project_slug")

    if not db or not project_id:
        return error_output(
            message="Missing required context", suggestion="Ensure db and project_id are in context"
        )

    try:
        from ....models import Container

        # Parse optional parameters
        base_id = params.get("base_id")
        container_type = params.get("container_type", "base")
        service_slug = params.get("service_slug")
        position_x = float(params.get("position_x", 0))
        position_y = float(params.get("position_y", 0))
        port = params.get("port")

        # Generate directory name from name
        directory = name.lower().replace(" ", "-").replace("_", "-")

        # Generate container name
        container_name = f"{project_slug}-{directory}" if project_slug else directory

        # Create container
        container = Container(
            id=uuid4(),
            project_id=project_id,
            base_id=UUID(base_id) if base_id else None,
            name=name,
            directory=directory,
            container_name=container_name,
            container_type=container_type,
            service_slug=service_slug if container_type == "service" else None,
            position_x=position_x,
            position_y=position_y,
            port=port,
        )

        db.add(container)
        await db.commit()
        await db.refresh(container)

        return success_output(
            message=f"Added container '{name}' to the grid",
            container_id=str(container.id),
            name=container.name,
            directory=container.directory,
            container_type=container_type,
            position={"x": position_x, "y": position_y},
        )

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to add container: {e}", exc_info=True)
        return error_output(
            message=f"Failed to add container: {str(e)}",
            suggestion="Check the container configuration",
        )


async def graph_add_browser_preview_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """
    Add a browser preview node to the grid.

    Args:
        params: {
            "container_id": "uuid of container to preview (optional)",
            "position_x": 100,
            "position_y": 200
        }
        context: Execution context

    Returns:
        Success/error output with preview info
    """
    db = context.get("db")
    project_id = context.get("project_id")

    if not db or not project_id:
        return error_output(
            message="Missing required context", suggestion="Ensure db and project_id are in context"
        )

    try:
        from ....models import BrowserPreview

        container_id = params.get("container_id")
        position_x = float(params.get("position_x", 400))
        position_y = float(params.get("position_y", 0))

        # Create browser preview
        preview = BrowserPreview(
            id=uuid4(),
            project_id=project_id,
            connected_container_id=UUID(container_id) if container_id else None,
            position_x=position_x,
            position_y=position_y,
            current_path="/",
        )

        db.add(preview)
        await db.commit()
        await db.refresh(preview)

        return success_output(
            message="Added browser preview to the grid",
            preview_id=str(preview.id),
            connected_container_id=container_id,
            position={"x": position_x, "y": position_y},
        )

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to add browser preview: {e}", exc_info=True)
        return error_output(
            message=f"Failed to add browser preview: {str(e)}",
            suggestion="Check the container_id if provided",
        )


async def graph_add_connection_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """
    Create a connection between two containers.

    Args:
        params: {
            "source_container_id": "uuid",
            "target_container_id": "uuid",
            "connector_type": "env_injection" | "http_api" | "database" | "cache" | "depends_on",
            "label": "optional label",
            "config": {} optional configuration
        }
        context: Execution context

    Returns:
        Success/error output with connection info
    """
    source_id = params.get("source_container_id")
    target_id = params.get("target_container_id")

    if not source_id or not target_id:
        return error_output(
            message="source_container_id and target_container_id are required",
            suggestion="Provide UUIDs for both containers",
        )

    db = context.get("db")
    project_id = context.get("project_id")

    if not db or not project_id:
        return error_output(
            message="Missing required context", suggestion="Ensure db and project_id are in context"
        )

    try:
        from sqlalchemy import select

        from ....models import Container, ContainerConnection

        # Verify both containers exist
        source_result = await db.execute(
            select(Container)
            .where(Container.id == UUID(source_id))
            .where(Container.project_id == project_id)
        )
        source = source_result.scalar_one_or_none()

        target_result = await db.execute(
            select(Container)
            .where(Container.id == UUID(target_id))
            .where(Container.project_id == project_id)
        )
        target = target_result.scalar_one_or_none()

        if not source:
            return error_output(
                message=f"Source container {source_id} not found",
                suggestion="Check the source_container_id",
            )

        if not target:
            return error_output(
                message=f"Target container {target_id} not found",
                suggestion="Check the target_container_id",
            )

        connector_type = params.get("connector_type", "env_injection")
        label = params.get("label")
        config = params.get("config", {})

        # Create connection
        connection = ContainerConnection(
            id=uuid4(),
            project_id=project_id,
            source_container_id=UUID(source_id),
            target_container_id=UUID(target_id),
            connector_type=connector_type,
            connection_type=connector_type,  # Legacy field
            label=label,
            config=config,
        )

        db.add(connection)
        await db.commit()
        await db.refresh(connection)

        return success_output(
            message=f"Created connection from '{source.name}' to '{target.name}'",
            connection_id=str(connection.id),
            source=source.name,
            target=target.name,
            connector_type=connector_type,
        )

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to add connection: {e}", exc_info=True)
        return error_output(
            message=f"Failed to add connection: {str(e)}",
            suggestion="Check container IDs and try again",
        )


async def graph_remove_item_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """
    Remove an item (container, connection, or browser preview) from the grid.

    Args:
        params: {
            "item_type": "container" | "connection" | "browser_preview",
            "item_id": "uuid"
        }
        context: Execution context

    Returns:
        Success/error output
    """
    item_type = params.get("item_type")
    item_id = params.get("item_id")

    if not item_type or not item_id:
        return error_output(
            message="item_type and item_id are required",
            suggestion="Specify the type and ID of the item to remove",
        )

    valid_types = ["container", "connection", "browser_preview"]
    if item_type not in valid_types:
        return error_output(
            message=f"Invalid item_type: {item_type}",
            suggestion=f"Use one of: {', '.join(valid_types)}",
        )

    db = context.get("db")
    project_id = context.get("project_id")

    if not db or not project_id:
        return error_output(
            message="Missing required context", suggestion="Ensure db and project_id are in context"
        )

    try:
        from sqlalchemy import delete

        from ....models import BrowserPreview, Container, ContainerConnection

        item_uuid = UUID(item_id)

        if item_type == "container":
            # Delete container (cascade will handle connections)
            result = await db.execute(
                delete(Container)
                .where(Container.id == item_uuid)
                .where(Container.project_id == project_id)
            )
            if result.rowcount == 0:
                return error_output(
                    message=f"Container {item_id} not found", suggestion="Check the item_id"
                )
            await db.commit()
            return success_output(message=f"Removed container {item_id}")

        elif item_type == "connection":
            result = await db.execute(
                delete(ContainerConnection)
                .where(ContainerConnection.id == item_uuid)
                .where(ContainerConnection.project_id == project_id)
            )
            if result.rowcount == 0:
                return error_output(
                    message=f"Connection {item_id} not found", suggestion="Check the item_id"
                )
            await db.commit()
            return success_output(message=f"Removed connection {item_id}")

        elif item_type == "browser_preview":
            result = await db.execute(
                delete(BrowserPreview)
                .where(BrowserPreview.id == item_uuid)
                .where(BrowserPreview.project_id == project_id)
            )
            if result.rowcount == 0:
                return error_output(
                    message=f"Browser preview {item_id} not found", suggestion="Check the item_id"
                )
            await db.commit()
            return success_output(message=f"Removed browser preview {item_id}")

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to remove item: {e}", exc_info=True)
        return error_output(
            message=f"Failed to remove item: {str(e)}", suggestion="Check item type and ID"
        )


# Tool definitions
GRID_TOOLS: list[Tool] = [
    Tool(
        name="graph_add_container",
        description="Add a new container node to the architecture grid. Creates a container in the project.",
        category=ToolCategory.PROJECT,
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Display name for the container (e.g., 'frontend', 'api')",
                },
                "base_id": {
                    "type": "string",
                    "description": "Optional UUID of marketplace base to use",
                },
                "container_type": {
                    "type": "string",
                    "enum": ["base", "service"],
                    "description": "Type: 'base' for app containers, 'service' for infra (postgres, redis)",
                },
                "service_slug": {
                    "type": "string",
                    "description": "For service type: 'postgres', 'redis', 'nginx', etc.",
                },
                "position_x": {"type": "number", "description": "X position on the canvas"},
                "position_y": {"type": "number", "description": "Y position on the canvas"},
                "port": {"type": "integer", "description": "Exposed port for the container"},
            },
            "required": ["name"],
        },
        executor=graph_add_container_executor,
        # Container spec in, new container_id dict out — JSON-clean.
        state_serializable=True,
        # Single DB write; no in-tool persistent handle.
        holds_external_state=False,
        examples=[
            '{"tool_name": "graph_add_container", "parameters": {"name": "frontend", "container_type": "base", "port": 3000}}',
            '{"tool_name": "graph_add_container", "parameters": {"name": "postgres", "container_type": "service", "service_slug": "postgres"}}',
        ],
    ),
    Tool(
        name="graph_add_browser_preview",
        description="Add a browser preview node to view container output in an embedded browser.",
        category=ToolCategory.PROJECT,
        parameters={
            "type": "object",
            "properties": {
                "container_id": {
                    "type": "string",
                    "description": "UUID of container to preview (optional, can connect later)",
                },
                "position_x": {"type": "number", "description": "X position on the canvas"},
                "position_y": {"type": "number", "description": "Y position on the canvas"},
            },
            "required": [],
        },
        executor=graph_add_browser_preview_executor,
        # Optional container_id + position in, preview_id dict out — JSON-clean.
        state_serializable=True,
        # Single DB write; no in-tool state.
        holds_external_state=False,
        examples=[
            '{"tool_name": "graph_add_browser_preview", "parameters": {"container_id": "abc-123", "position_x": 400}}'
        ],
    ),
    Tool(
        name="graph_add_connection",
        description="Create a connection between two containers (dependency, environment injection, API connection).",
        category=ToolCategory.PROJECT,
        parameters={
            "type": "object",
            "properties": {
                "source_container_id": {
                    "type": "string",
                    "description": "UUID of the source container",
                },
                "target_container_id": {
                    "type": "string",
                    "description": "UUID of the target container",
                },
                "connector_type": {
                    "type": "string",
                    "enum": ["env_injection", "http_api", "database", "cache", "depends_on"],
                    "description": "Type of connection",
                },
                "label": {"type": "string", "description": "Optional label for the connection"},
                "config": {
                    "type": "object",
                    "description": "Optional configuration for the connection",
                },
            },
            "required": ["source_container_id", "target_container_id"],
        },
        executor=graph_add_connection_executor,
        # Source/target/type in, connection_id dict out — JSON-clean.
        state_serializable=True,
        # Single DB write; no in-tool state.
        holds_external_state=False,
        examples=[
            '{"tool_name": "graph_add_connection", "parameters": {"source_container_id": "abc", "target_container_id": "def", "connector_type": "database"}}'
        ],
    ),
    Tool(
        name="graph_remove_item",
        description="Remove a container, connection, or browser preview from the grid.",
        category=ToolCategory.PROJECT,
        parameters={
            "type": "object",
            "properties": {
                "item_type": {
                    "type": "string",
                    "enum": ["container", "connection", "browser_preview"],
                    "description": "Type of item to remove",
                },
                "item_id": {"type": "string", "description": "UUID of the item to remove"},
            },
            "required": ["item_type", "item_id"],
        },
        executor=graph_remove_item_executor,
        # item_type + item_id in, success dict out — JSON-clean.
        state_serializable=True,
        # Single DB delete; no in-tool state.
        holds_external_state=False,
        examples=[
            '{"tool_name": "graph_remove_item", "parameters": {"item_type": "container", "item_id": "abc-123"}}'
        ],
    ),
]
