# Project Control Tool

Container lifecycle management tool for the code-view agent. Wraps orchestrator APIs so the agent can manage containers by name (from `.tesslate/config.json`) rather than UUIDs. Available to all agents regardless of view.

## Tool Overview

| Tool | Purpose | Parameters |
|------|---------|------------|
| `project_control` | Container lifecycle control | action, container_name (optional) |

## project_control

**File**: `orchestrator/app/agent/tools/project_ops/project_control.py`

Dispatches container lifecycle actions against the current project. Containers are referenced by their human-readable name as defined in `.tesslate/config.json`, not by database UUID. The tool resolves names to Container models internally and delegates to the active orchestrator (Docker Compose or Kubernetes).

### Parameters

```python
{
    "action": "status",           # Required: one of the actions below
    "container_name": "backend"   # Required for: restart_container, container_logs, health_check
}
```

### Actions

| Action | Description | `container_name` required? |
|--------|-------------|---------------------------|
| `status` | List all containers with running state, URLs, and ports | No |
| `restart_container` | Stop then start a single container by name | Yes |
| `restart_all` | Restart every container in the project | No |
| `reload_config` | Re-read `.tesslate/config.json` and sync Container DB records | No |
| `container_logs` | Tail the last 100 lines from a container (capped at 50 KB) | Yes |
| `health_check` | HTTP GET probe against a container's dev-server port | Yes |

### Returns

**status** (success):
```python
{
    "success": True,
    "tool": "project_control",
    "result": {
        "message": "Found 2 container(s)",
        "project_status": "active",
        "containers": [
            {"name": "frontend", "directory": "app", "status": "running", "url": "https://...", "port": 3000},
            {"name": "backend", "directory": "server", "status": "running", "url": "https://...", "port": 8000}
        ]
    }
}
```

**restart_container** (success):
```python
{
    "success": True,
    "tool": "project_control",
    "result": {
        "message": "Container 'backend' restarted successfully",
        "container_name": "backend",
        "url": "https://...",
        "status": "starting"
    }
}
```

**Error** (container not found):
```python
{
    "success": False,
    "tool": "project_control",
    "result": {
        "message": "Container 'api' not found in this project",
        "suggestion": "Use the 'status' action to list available container names"
    }
}
```

## Code View vs Graph View

Two separate tool surfaces provide container management for different UI contexts:

- **`graph_ops/containers.py`** provides container tools for the **graph/architecture canvas**. These are UUID-based, view-scoped tools (e.g., `graph_start_container`, `graph_stop_container`) registered only when the user is in graph view.
- **`project_control`** provides container tools for the **code view**. It uses human-readable names from `.tesslate/config.json` and is available to all agents regardless of the active view.

Both tool surfaces delegate to the same underlying orchestrator (`get_orchestrator()`) and produce equivalent results. The distinction is purely about how the agent references containers: UUIDs in graph view vs names in code view.

## Implementation Notes

- **Name resolution**: `_lookup_container_by_name()` queries the Container table by `name + project_id`.
- **Directory resolution**: `_resolve_container_dir()` reads live K8s pod labels first (source of truth), falling back to `resolve_k8s_container_dir()` for the sanitised `container.directory`. It never derives directory from `container.name`.
- **reload_config**: Parses the config via `parse_tesslate_config()`, upserts Container rows, and deletes orphaned base containers no longer present in the config file.
- **Logs truncation**: Output is capped at 50 KB (`_MAX_LOG_BYTES`) to avoid blowing up agent context.

## Related Documentation

- [../../services/config-json.md](../../services/config-json.md) -- Config.json schema and lifecycle
- [skill-ops.md](skill-ops.md) -- Skill system (Project Architecture skill)
- [registry.md](registry.md) -- Tool registry
- [graph-ops.md](graph-ops.md) -- Graph view container tools
