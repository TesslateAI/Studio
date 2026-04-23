# Schedule Tool (`schedule_ops/`)

Single tool (`manage_schedule`) that lets an agent create, list, update, pause, resume, trigger, and delete cron-scheduled agent tasks from within a conversation.

## File

`schedule_ops/manage_schedule.py` exposes `manage_schedule_executor` and `register_schedule_ops_tools(registry)`.

> Note: the subpackage's `__init__.py` only has a docstring. The register function is imported directly from `manage_schedule.py` by `tools/registry.py::_register_all_tools`.

## Actions

| Action | Required fields |
|--------|-----------------|
| `create` | `name`, `schedule` (natural language or cron), `prompt`, optional `deliver` (default `origin`) |
| `list` | (none) |
| `update` | `job_id`, any of `name`, `schedule`, `prompt`, `deliver` |
| `pause` | `job_id` |
| `resume` | `job_id` |
| `trigger` | `job_id` (immediate test run) |
| `delete` | `job_id` |

## Dependencies

- `user_id` and `project_id` from execution context.
- DB session via `context["db"]`.
- Natural-language-to-cron parsing delegates to `orchestrator/app/services/gateway/schedule_parser.py::parse_schedule`.
- Schedules are persisted as `AgentSchedule` rows and executed by `orchestrator/app/services/gateway/scheduler.py`.

## Related

- `docs/orchestrator/routers/CLAUDE.md` → schedules.py for the HTTP API equivalent.
- `docs/orchestrator/services/gateway/` for the scheduler and trigger dispatch.
