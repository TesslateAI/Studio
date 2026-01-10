# Graph Tools Quick Reference

## Graph-Specific Tools

These tools are ONLY available when `viewContext="graph"`:

### Container Control

```json
// Start a container
{
  "tool_name": "graph_start_container",
  "parameters": { "container_id": "uuid-here" }
}

// Stop a container
{
  "tool_name": "graph_stop_container",
  "parameters": { "container_id": "uuid-here" }
}

// Start all containers
{
  "tool_name": "graph_start_all",
  "parameters": {}
}

// Stop all containers
{
  "tool_name": "graph_stop_all",
  "parameters": {}
}

// Get container status
{
  "tool_name": "graph_container_status",
  "parameters": {}
}
```

### Grid Management

```json
// Add a container to the grid
{
  "tool_name": "graph_add_container",
  "parameters": {
    "name": "frontend",
    "container_type": "base",
    "port": 3000,
    "position_x": 100,
    "position_y": 200
  }
}

// Add a service container
{
  "tool_name": "graph_add_container",
  "parameters": {
    "name": "postgres",
    "container_type": "service",
    "service_slug": "postgres"
  }
}

// Add browser preview
{
  "tool_name": "graph_add_browser_preview",
  "parameters": {
    "container_id": "uuid-of-container-to-preview",
    "position_x": 400,
    "position_y": 0
  }
}

// Create connection between containers
{
  "tool_name": "graph_add_connection",
  "parameters": {
    "source_container_id": "uuid",
    "target_container_id": "uuid",
    "connector_type": "database"
  }
}

// Remove an item
{
  "tool_name": "graph_remove_item",
  "parameters": {
    "item_type": "container",
    "item_id": "uuid"
  }
}
```

### Shell Access

```json
// Open shell in specific container
{
  "tool_name": "graph_shell_open",
  "parameters": { "container_id": "uuid" }
}

// Execute command in specific container
{
  "tool_name": "graph_shell_exec",
  "parameters": {
    "container_id": "uuid",
    "command": "npm install",
    "timeout": 120
  }
}

// Close shell session
{
  "tool_name": "graph_shell_close",
  "parameters": { "session_id": "session-uuid" }
}
```

## View Contexts

| View Context | Available Tools |
|--------------|-----------------|
| `graph` | All base tools + graph_* tools |
| `builder` | Base tools only (read_file, write_file, bash_exec, etc.) |
| `terminal` | Base tools (future: terminal-specific tools) |
| `kanban` | Base tools (future: kanban-specific tools) |

## Connector Types for Connections

| Type | Description |
|------|-------------|
| `env_injection` | Environment variable injection |
| `http_api` | HTTP/REST API connection |
| `database` | Database connection |
| `cache` | Cache (Redis) connection |
| `depends_on` | Startup dependency |

## Response Format

All graph tools return standardized responses:

```json
// Success
{
  "success": true,
  "message": "Human-readable success message",
  // ... additional data fields
}

// Error
{
  "success": false,
  "message": "Error description",
  "suggestion": "How to fix it"
}
```
