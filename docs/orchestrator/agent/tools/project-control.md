# Project Lifecycle & Config Tools

Agent tools that drive the project's config graph and container lifecycle. They all live under `orchestrator/app/agent/tools/project_ops/`. Containers are referenced by their name in `.tesslate/config.json`, not by UUID.

## Tool Inventory

| Tool | File | Purpose |
|------|------|---------|
| `apply_setup_config` | `setup_config.py` | Write `.tesslate/config.json` + replace the full graph (containers, connections, deployments, previews) atomically |
| `project_start` | `project_lifecycle.py` | Start every container in the project |
| `project_stop` | `project_lifecycle.py` | Stop every container; also closes active shell sessions |
| `project_restart` | `project_lifecycle.py` | Stop + start in one call |
| `container_start` | `container_lifecycle.py` | Start a single container by name |
| `container_stop` | `container_lifecycle.py` | Stop a single container by name |
| `container_restart` | `container_lifecycle.py` | Stop + start a single container |
| `project_control` | `project_control.py` | **Observation only** — status, container_logs, health_check |

Shared lookups live in `project_ops/_helpers.py` (`fetch_project`, `fetch_all_containers`, `fetch_connections`, `lookup_container_by_name`, `resolve_container_dir`, `require_project_context`).

## `apply_setup_config` — the canonical way to edit config

Calls `services/config_sync.py:sync_project_config` — the same function the UI's `POST /{slug}/setup-config` hits. Writes the file AND replaces the container/connection/deployment/preview graph in one transaction. Startup commands are validated; bad commands fail the call and nothing is written.

**Use this instead of `write_file` when editing `.tesslate/config.json`.** `write_file` still works for raw edits but does not sync the graph — previous versions silently synced app containers only and dropped infra, connections, deployments, and previews. That behavior has been removed.

**Config parameter schema**: the tool's `config` parameter carries the full Pydantic JSON Schema of `TesslateConfigCreate` directly — the agent sees the exact shape the endpoint accepts. For field semantics, the infrastructure service catalog, startup-command validation rules, deployment compatibility matrix, and worked examples, the agent loads the built-in skill `project-architecture` via `load_skill('project-architecture')`. That skill is always available — no user install required. See [../../services/skill-discovery.md](../../services/skill-discovery.md).

**Params**
```jsonc
{
  "config": {
    "apps": {
      "frontend": {"directory": "frontend", "port": 3000, "start": "npm run dev"}
    },
    "infrastructure": {
      "postgres": {"port": 5432, "type": "container"}
    },
    "connections": [{"from_node": "frontend", "to_node": "postgres"}],
    "deployments": {},
    "previews": {},
    "primaryApp": "frontend"
  }
}
```

**Returns**
```python
{"success": True, "container_ids": ["uuid", ...], "primary_container_id": "uuid"}
```

## Lifecycle tools

All lifecycle tools take project context from the agent execution context (no params needed) except the per-container ones, which take `container_name`.

| Tool | Params | Wraps |
|------|--------|-------|
| `project_start` | `{}` | `orchestrator.start_project(...)` |
| `project_stop` | `{}` | `orchestrator.stop_project(...)` (closes shell sessions first, sets `environment_status=stopped`) |
| `project_restart` | `{}` | `orchestrator.restart_project(...)` |
| `container_start` | `{container_name}` | Fast-path: if Docker and running, returns URL. Otherwise `orchestrator.start_container(...)` |
| `container_stop` | `{container_name}` | `orchestrator.stop_container(...)` (K8s service-slug case handled) |
| `container_restart` | `{container_name}` | stop + start |

## `project_control` — observation only

| Action | Params | Purpose |
|--------|--------|---------|
| `status` | — | List containers with running state, URLs, ports |
| `container_logs` | `container_name` | Tail last 100 lines (capped at 50 KB) |
| `health_check` | `container_name` | HTTP GET probe against the container port |

Lifecycle actions (`restart_container`, `restart_all`, `reload_config`) have been removed — use the dedicated tools above.

## Code View vs Graph View

Two separate tool surfaces manage containers for different UI contexts:

- **`graph_ops/containers.py`** — graph/architecture canvas. UUID-based, view-scoped.
- **`project_ops/*`** (this doc) — code view. Name-based from `.tesslate/config.json`, available to all agents.

Both delegate to the same `get_orchestrator()` backend.

## Typical agent flows

**"Add Postgres and wire frontend to it"**
```
1. write_file                  -- optional: draft file for review
2. apply_setup_config          -- single source of truth for graph sync
3. project_start               -- bring stack up
```

**"Restart frontend after env change"**
```
1. apply_setup_config          -- if env changed in config.json
2. container_restart(frontend)
```

**"What's running?"**
```
1. project_control(status)
```

## Implementation Notes

- **Name resolution**: `lookup_container_by_name()` queries Container by `name + project_id` (see `_helpers.py`).
- **K8s directory**: `resolve_container_dir()` reads live pod labels first, falls back to `resolve_k8s_container_dir()`. Never derives directory from `container.name`.
- **apply_setup_config vs write_file auto-sync**: `write_file` used to silently sync containers when you wrote `.tesslate/config.json` — but only apps, not infra/connections/deployments/previews, and it swallowed validation errors. That auto-sync has been removed in favor of `apply_setup_config`.
- **Log truncation**: Output capped at 50 KB (`_MAX_LOG_BYTES`) so logs don't blow up context.

## Related Documentation

- [../../services/config-json.md](../../services/config-json.md) — config.json schema & lifecycle
- [registry.md](registry.md) — tool registry
- [graph-ops.md](graph-ops.md) — graph view container tools
