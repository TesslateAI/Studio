# Planning Tools (`planning_ops/`)

Tools for task planning and run-scoped plans. None of these are in `DANGEROUS_TOOLS`: they are explicitly safe in plan mode (they are how plan mode is expressed).

## Tools

| Tool | File | Purpose |
|------|------|---------|
| `todo_read` | `planning_ops/todos.py` | Read the current loose task list for a conversation session. |
| `todo_write` | `planning_ops/todos.py` | Replace / update the task list. |
| `save_plan` | `planning_ops/plan_tools.py` | Save a new plan via `services.plan_manager.PlanManager`. Called by the Plan subagent or the main agent in plan mode. |
| Legacy `update_plan` | `planning_ops/plan_tools.py` | Step-progress tracker backed by `PlanManager`. Kept for backwards compatibility. |
| Structured `update_plan` | `planning_ops/update_plan.py` | New structured plan tool with per-run `PlanStore` and file mirror at `.tesslate/plan.json`. Emits events to connected sinks (SSE pipeline). |

## Persistence

- **Todos** (`todos.py`): in-memory per `conversation_id`/`session_id`, mirrored to Redis with 24-hour TTL so API and worker pods see the same list.
- **Legacy plans** (`plan_tools.py`): routed through `PlanManager` (see `orchestrator/app/services/plan_manager.py`), which persists to Redis for cross-pod visibility.
- **Structured plans** (`update_plan.py`): per-process `PlanStore` keyed by `run_id`; mirrored to `<project_root>/.tesslate/plan.json` via `orchestrator.write_file` so Docker, Kubernetes, and Local backends see the same file.

## Registration

`register_all_planning_tools(registry)` calls:

| Function | Tools |
|----------|-------|
| `register_planning_tools` | `todo_read`, `todo_write` |
| `register_plan_tools` | `save_plan`, legacy `update_plan` |
| `register_update_plan_tool` | structured `update_plan` |

## Related

- `orchestrator/app/services/plan_manager.py`: legacy plan persistence.
- `docs/packages/CLAUDE.md`: how the runner coordinates `PlanStore` events with the streaming UI.
