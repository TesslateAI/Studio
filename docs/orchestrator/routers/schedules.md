# Schedules Router

**File**: `orchestrator/app/routers/schedules.py`

**Base path**: `/api/schedules`

## Purpose

CRUD and lifecycle for cron-scheduled agent tasks. Schedules are evaluated by the gateway process's `CronScheduler`; when a schedule fires, the stored prompt is enqueued as an agent task whose result is routed back through the originating channel.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `` | user | Create a schedule. Validates project access, enforces per-user limit, parses natural-language or cron via `schedule_parser.parse_schedule()`. |
| GET | `` | user | List schedules for the current user (filter by `project_id`). |
| GET | `/{schedule_id}` | user | Fetch a single schedule. |
| PATCH | `/{schedule_id}` | user | Update; re-parses cron when `schedule` field changes. |
| DELETE | `/{schedule_id}` | user | Delete schedule. |
| POST | `/{schedule_id}/pause` | user | Set `is_active=False`. |
| POST | `/{schedule_id}/resume` | user | Set `is_active=True`, recompute `next_run_at`. |
| POST | `/{schedule_id}/trigger` | user | Fire immediately as a test run (creates a Chat + Message, enqueues via ARQ). |

## Auth

All endpoints require `current_active_user` and verify project access.

## Related

- Model: `AgentSchedule` in [models.py](../../../orchestrator/app/models.py).
- Parser: `orchestrator/app/services/gateway/schedule_parser.py`.
- Scheduler: `orchestrator/app/services/gateway/scheduler.py`.
- Agent tool equivalent: `schedule_ops/manage_schedule.py` (see [../agent/tools/CLAUDE.md](../agent/tools/CLAUDE.md)).
