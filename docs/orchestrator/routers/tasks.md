# Tasks Router

**File**: `orchestrator/app/routers/tasks.py`

**Base path**: `/api/tasks`

## Purpose

Background-task status API for long-running work (project setup, agent runs, deployments). Combines in-process `TaskManager` state with Redis-backed cross-pod lookups so any pod can answer about any task.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/{task_id}/status` | user | Return `{ status, progress, total, message, result }`. |
| GET | `/user/active` | user | Active tasks for the current user. |
| GET | `/user/all` | user | All tasks (active + completed) with a `limit` (default 50). |
| DELETE | `/{task_id}` | user | Cancel a running task (best-effort; sets cancellation signal in Redis). |
| WS | `/ws` | user | WebSocket for real-time task progress events (subscribes per task id). |

## Auth

All endpoints require `current_active_user`; results are scoped to tasks owned by the caller.

## Related

- Service: [../../../orchestrator/app/services/task_manager.py](../../../orchestrator/app/services/task_manager.py).
- Pub/sub: [../services/pubsub.md](../services/pubsub.md).
- Worker: [../services/worker.md](../services/worker.md).
