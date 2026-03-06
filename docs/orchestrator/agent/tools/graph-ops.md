# Graph Operation Tools

**Files**: `orchestrator/app/agent/tools/graph_ops/`

Graph operation tools enable agents to manage containers when users are viewing the architecture graph canvas. These tools are only available in graph/architecture view.

## Overview

Graph tools allow agents to:
- Start/stop individual containers
- Start/stop all containers
- Add containers to the grid
- Create connections between containers
- Add browser preview nodes
- Remove grid items

## Tool Categories

### Container Lifecycle (5 tools)
- `graph_start_container` - Start specific container
- `graph_stop_container` - Stop specific container
- `graph_start_all` - Start all containers
- `graph_stop_all` - Stop all containers
- `graph_container_status` - Get container status

### Grid Management (4 tools)
- `graph_add_container` - Add container node to grid
- `graph_add_browser_preview` - Add browser preview node
- `graph_add_connection` - Create connection between containers
- `graph_remove_item` - Remove grid item

## Container Lifecycle Tools

### graph_start_container

**File**: `orchestrator/app/agent/tools/graph_ops/containers.py`

Start a specific container by ID.

#### Parameters

```python
{
    "container_id": "abc-123-def-456"  # UUID of container
}
```

#### Returns

```python
# Success
{
    "success": True,
    "tool": "graph_start_container",
    "result": {
        "message": "Container 'frontend' started successfully",
        "container_id": "abc-123-def-456",
        "container_name": "frontend",
        "url": "https://frontend.myapp.your-domain.com",
        "status": "starting"
    }
}

# Error
{
    "success": False,
    "tool": "graph_start_container",
    "error": "Container abc-123-def-456 not found",
    "result": {
        "message": "Container not found",
        "suggestion": "Check the container_id is correct"
    }
}
```

#### Implementation

```python
async def graph_start_container_executor(
    params: Dict[str, Any],
    context: Dict[str, Any]
) -> Dict[str, Any]:
    container_id = params.get("container_id")
    if not container_id:
        return error_output(message="container_id is required", ...)

    db = context.get("db")
    user_id = context.get("user_id")
    project_id = context.get("project_id")

    # Fetch container with relationships
    container_result = await db.execute(
        select(Container)
        .where(Container.id == UUID(container_id))
        .where(Container.project_id == project_id)
        .options(selectinload(Container.base))
    )
    container = container_result.scalar_one_or_none()

    if not container:
        return error_output(message=f"Container {container_id} not found", ...)

    # Start container via orchestrator
    orchestrator = get_orchestrator()
    result = await orchestrator.start_container(
        project=project,
        container=container,
        all_containers=all_containers,
        connections=connections,
        user_id=user_id,
        db=db
    )

    return success_output(
        message=f"Container '{container.name}' started successfully",
        container_id=str(container.id),
        container_name=container.name,
        url=result.get("url"),
        status="starting"
    )
```

#### Usage Example

```python
THOUGHT: The user wants to start the frontend container.

{
  "tool_name": "graph_start_container",
  "parameters": {
    "container_id": "abc-123-def-456"
  }
}
```

### graph_stop_container

Stop a specific container by ID.

#### Parameters

```python
{
    "container_id": "abc-123-def-456"
}
```

#### Returns

```python
{
    "success": True,
    "tool": "graph_stop_container",
    "result": {
        "message": "Container 'frontend' stopped successfully",
        "container_id": "abc-123-def-456",
        "container_name": "frontend",
        "status": "stopped"
    }
}
```

### graph_start_all

Start all containers in the project.

#### Parameters

```python
{}  # No parameters needed
```

#### Returns

```python
{
    "success": True,
    "tool": "graph_start_all",
    "result": {
        "message": "Started 3 containers",
        "containers": {
            "frontend": {"url": "https://frontend.myapp...", "status": "starting"},
            "backend": {"url": "https://backend.myapp...", "status": "starting"},
            "postgres": {"url": null, "status": "starting"}
        },
        "namespace": "proj-abc123",
        "network": "myapp-network"
    }
}
```

#### Usage Example

```python
THOUGHT: The user wants to launch the entire application.

{
  "tool_name": "graph_start_all",
  "parameters": {}
}
```

### graph_stop_all

Stop all containers in the project.

#### Parameters

```python
{}  # No parameters needed
```

#### Returns

```python
{
    "success": True,
    "tool": "graph_stop_all",
    "result": {
        "message": "All containers stopped successfully",
        "project_slug": "myapp-k3x8n2"
    }
}
```

### graph_container_status

Get status of all containers in the project.

#### Parameters

```python
{}  # No parameters needed
```

#### Returns

```python
{
    "success": True,
    "tool": "graph_container_status",
    "result": {
        "message": "Found 3 containers",
        "project_status": "running",
        "containers": [
            {
                "id": "abc-123",
                "name": "frontend",
                "directory": "frontend",
                "status": "running",
                "url": "https://frontend.myapp...",
                "port": 3000
            },
            {
                "id": "def-456",
                "name": "backend",
                "directory": "backend",
                "status": "running",
                "url": "https://backend.myapp...",
                "port": 8000
            },
            {
                "id": "ghi-789",
                "name": "postgres",
                "directory": "postgres",
                "status": "stopped",
                "url": null,
                "port": 5432
            }
        ]
    }
}
```

#### Usage Example

```python
THOUGHT: I'll check which containers are currently running.

{
  "tool_name": "graph_container_status",
  "parameters": {}
}
```

## Grid Management Tools

### graph_add_container

**File**: `orchestrator/app/agent/tools/graph_ops/grid.py`

Add a new container node to the architecture grid.

#### Parameters

```python
{
    "name": "frontend",               # Display name
    "base_id": "abc-123",              # Optional marketplace base UUID
    "container_type": "base",          # "base" or "service"
    "service_slug": "postgres",        # For service type
    "position_x": 100,                 # Canvas X position
    "position_y": 200,                 # Canvas Y position
    "port": 3000                       # Exposed port
}
```

#### Container Types

- **base**: Application containers (frontend, backend, etc.)
- **service**: Infrastructure services (postgres, redis, nginx)

#### Returns

```python
{
    "success": True,
    "tool": "graph_add_container",
    "result": {
        "message": "Added container 'frontend' to the grid",
        "container_id": "new-uuid",
        "name": "frontend",
        "directory": "frontend",
        "container_type": "base",
        "position": {"x": 100, "y": 200}
    }
}
```

#### Usage Example

```python
# Add application container
{
  "tool_name": "graph_add_container",
  "parameters": {
    "name": "frontend",
    "container_type": "base",
    "port": 3000,
    "position_x": 100,
    "position_y": 100
  }
}

# Add database service
{
  "tool_name": "graph_add_container",
  "parameters": {
    "name": "postgres",
    "container_type": "service",
    "service_slug": "postgres",
    "position_x": 400,
    "position_y": 100
  }
}
```

### graph_add_browser_preview

Add a browser preview node to view container output.

#### Parameters

```python
{
    "container_id": "abc-123",   # Optional, can connect later
    "position_x": 400,
    "position_y": 0
}
```

#### Returns

```python
{
    "success": True,
    "tool": "graph_add_browser_preview",
    "result": {
        "message": "Added browser preview to the grid",
        "preview_id": "preview-uuid",
        "connected_container_id": "abc-123",
        "position": {"x": 400, "y": 0}
    }
}
```

### graph_add_connection

Create a connection between two containers.

#### Parameters

```python
{
    "source_container_id": "abc-123",
    "target_container_id": "def-456",
    "connector_type": "env_injection",  # Type of connection
    "label": "DATABASE_URL",             # Optional label
    "config": {}                         # Optional configuration
}
```

#### Connector Types

- `env_injection` - Environment variable injection
- `http_api` - HTTP API connection
- `database` - Database connection
- `cache` - Cache connection (Redis, etc.)
- `depends_on` - Startup dependency

#### Returns

```python
{
    "success": True,
    "tool": "graph_add_connection",
    "result": {
        "message": "Created connection from 'backend' to 'postgres'",
        "connection_id": "connection-uuid",
        "source": "backend",
        "target": "postgres",
        "connector_type": "database"
    }
}
```

#### Usage Example

```python
# Connect backend to database
{
  "tool_name": "graph_add_connection",
  "parameters": {
    "source_container_id": "backend-id",
    "target_container_id": "postgres-id",
    "connector_type": "database",
    "label": "DATABASE_URL"
  }
}

# Connect frontend to backend API
{
  "tool_name": "graph_add_connection",
  "parameters": {
    "source_container_id": "frontend-id",
    "target_container_id": "backend-id",
    "connector_type": "http_api",
    "label": "API_URL"
  }
}
```

### graph_remove_item

Remove a container, connection, or browser preview from the grid.

#### Parameters

```python
{
    "item_type": "container",      # "container", "connection", or "browser_preview"
    "item_id": "abc-123-def-456"   # UUID of item to remove
}
```

#### Returns

```python
{
    "success": True,
    "tool": "graph_remove_item",
    "result": {
        "message": "Removed container abc-123-def-456"
    }
}
```

#### Usage Examples

```python
# Remove container
{
  "tool_name": "graph_remove_item",
  "parameters": {
    "item_type": "container",
    "item_id": "abc-123"
  }
}

# Remove connection
{
  "tool_name": "graph_remove_item",
  "parameters": {
    "item_type": "connection",
    "item_id": "connection-uuid"
  }
}

# Remove browser preview
{
  "tool_name": "graph_remove_item",
  "parameters": {
    "item_type": "browser_preview",
    "item_id": "preview-uuid"
  }
}
```

## View-Scoped Access

Graph tools are only available when the user is viewing the architecture graph canvas.

### View-Scoped Tool Registry

```python
from orchestrator.app.agent.tools.view_scoped_factory import create_view_scoped_tools

# Code view: standard tools
if view == "code":
    tools = create_scoped_tool_registry([
        "read_file", "write_file", "bash_exec"
    ])

# Graph view: graph tools + limited file/shell tools
elif view == "graph":
    tools = create_view_scoped_tools(
        view="graph",
        project_id=project.id,
        user_id=user.id
    )
    # Includes: graph_start_container, graph_add_container, etc.
```

### GraphProvider

**File**: `orchestrator/app/agent/tools/providers/graph_provider.py`

Provides graph-specific tools with project context.

```python
class GraphProvider:
    def __init__(self, project_id: str, user_id: str):
        self.project_id = project_id
        self.user_id = user_id

    def get_tools(self) -> List[Tool]:
        """Return list of graph operation tools."""
        from ..graph_ops.containers import CONTAINER_TOOLS
        from ..graph_ops.grid import GRID_TOOLS

        return CONTAINER_TOOLS + GRID_TOOLS
```

## Complete Architecture Example

Building a full-stack application with graph tools:

```python
# 1. Check current status
{
  "tool_name": "graph_container_status",
  "parameters": {}
}

# 2. Add frontend container
{
  "tool_name": "graph_add_container",
  "parameters": {
    "name": "frontend",
    "container_type": "base",
    "port": 3000,
    "position_x": 100,
    "position_y": 100
  }
}
# Returns: {"container_id": "frontend-uuid"}

# 3. Add backend container
{
  "tool_name": "graph_add_container",
  "parameters": {
    "name": "backend",
    "container_type": "base",
    "port": 8000,
    "position_x": 300,
    "position_y": 100
  }
}
# Returns: {"container_id": "backend-uuid"}

# 4. Add PostgreSQL service
{
  "tool_name": "graph_add_container",
  "parameters": {
    "name": "postgres",
    "container_type": "service",
    "service_slug": "postgres",
    "position_x": 500,
    "position_y": 100
  }
}
# Returns: {"container_id": "postgres-uuid"}

# 5. Connect frontend to backend
{
  "tool_name": "graph_add_connection",
  "parameters": {
    "source_container_id": "frontend-uuid",
    "target_container_id": "backend-uuid",
    "connector_type": "http_api",
    "label": "API_URL"
  }
}

# 6. Connect backend to database
{
  "tool_name": "graph_add_connection",
  "parameters": {
    "source_container_id": "backend-uuid",
    "target_container_id": "postgres-uuid",
    "connector_type": "database",
    "label": "DATABASE_URL"
  }
}

# 7. Add browser preview for frontend
{
  "tool_name": "graph_add_browser_preview",
  "parameters": {
    "container_id": "frontend-uuid",
    "position_x": 700,
    "position_y": 100
  }
}

# 8. Start all containers
{
  "tool_name": "graph_start_all",
  "parameters": {}
}
```

## Best Practices

### 1. Check Status Before Operations

```python
# ✅ Good: Check status first
[
  {
    "tool_name": "graph_container_status",
    "parameters": {}
  },
  {
    "tool_name": "graph_start_container",
    "parameters": {"container_id": "abc"}
  }
]
```

### 2. Organize Grid Layout

```python
# ✅ Good: Space containers evenly
{
  "tool_name": "graph_add_container",
  "parameters": {
    "name": "frontend",
    "position_x": 100,  # Left side
    "position_y": 100
  }
}

{
  "tool_name": "graph_add_container",
  "parameters": {
    "name": "backend",
    "position_x": 400,  # Middle
    "position_y": 100
  }
}
```

### 3. Label Connections Clearly

```python
# ✅ Good: Descriptive labels
{
  "tool_name": "graph_add_connection",
  "parameters": {
    "source_container_id": "backend",
    "target_container_id": "postgres",
    "connector_type": "database",
    "label": "DATABASE_URL"  # Clear purpose
  }
}
```

### 4. Use Appropriate Connector Types

```python
# ✅ Good: Correct types
# API connection
{"connector_type": "http_api"}

# Database connection
{"connector_type": "database"}

# Environment injection
{"connector_type": "env_injection"}
```

## Related Files

- `orchestrator/app/agent/tools/graph_ops/containers.py` - Container lifecycle tools
- `orchestrator/app/agent/tools/graph_ops/grid.py` - Grid management tools
- `orchestrator/app/agent/tools/graph_ops/shell.py` - Shell operations in containers
- `orchestrator/app/agent/tools/providers/graph_provider.py` - Graph tool provider
- `orchestrator/app/agent/tools/view_scoped_factory.py` - View-scoped tool creation
- `orchestrator/app/models.py` - Container, ContainerConnection models
- `orchestrator/app/services/orchestration/` - Orchestration services
