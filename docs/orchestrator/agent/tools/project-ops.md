# Project Tools (`project_ops/`)

Tools for observing project state, mutating the project config graph, and controlling project + container lifecycle. Complements the narrower `project-control.md` doc.

## Files

| File | Tools |
|------|-------|
| `metadata.py` | `get_project_info` |
| `project_control.py` | `project_control` (observation only: `status`, `container_logs`, `health_check`, `tier_status`) |
| `setup_config.py` | `apply_setup_config` (writes `.tesslate/config.json` and atomically replaces the project graph) |
| `project_lifecycle.py` | `project_start`, `project_stop`, `project_restart` |
| `container_lifecycle.py` | `container_start`, `container_stop`, `container_restart` |
| `kanban.py` | `kanban` (see `kanban-agent-tool.md`) |
| `_helpers.py` | Shared lookups: `lookup_container_by_name`, `fetch_project`, etc. |

## Registration

`register_all_project_tools(registry)` registers everything in order: `metadata`, `project_control`, `setup_config`, `project_lifecycle`, `container_lifecycle`, `kanban`.

## Scope Enforcement

| Tool | Required scope (API-key) |
|------|--------------------------|
| `container_status`, `container_logs`, `container_health` | `container.view` |
| `container_restart` | `container.start_stop` |
| `kanban_create`, `kanban_move`, `kanban_update`, `kanban_comment` | `kanban.edit` |
| Others | No scope required |

## Lifecycle vs Control

- **Lifecycle tools** mutate state: they start/stop containers, rewrite the config graph, and trigger orchestrator actions.
- **`project_control` is observation only**: use it for `status`, `container_logs`, `health_check`, and compute-tier inspection (`tier_status`).

## Related

- `project-control.md`: deeper dive on observation.
- `kanban-agent-tool.md`: kanban sub-tool.
- `../routers/projects.py` setup-config endpoint: HTTP equivalent to `apply_setup_config`.
