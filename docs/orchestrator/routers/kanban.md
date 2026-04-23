# Kanban Router

**File**: `orchestrator/app/routers/kanban.py`

**Base path**: `/api/kanban`

## Purpose

Per-project kanban board (columns, tasks with `TSK-NNNN` refs, comments, project notes). Serves both the frontend board panel and the agent `kanban` tool.

## Endpoints

### Board + Columns

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/projects/{project_id}/board` | owner | Board snapshot (columns + tasks ordered). |
| POST | `/projects/{project_id}/columns` | owner | Create column. |
| PATCH | `/columns/{column_id}` | owner | Rename/reorder column. |
| DELETE | `/columns/{column_id}` | owner | Delete column. |

### Tasks

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/projects/{project_id}/tasks` | owner | Create task (assigns the next `TSK-NNNN` ref). |
| GET | `/tasks/{task_id}` | owner | Task detail (comments, history). |
| PATCH | `/tasks/{task_id}` | owner | Update fields (title, description, assignee, priority). |
| POST | `/tasks/{task_id}/move` | owner | Move to another column / reorder. |
| DELETE | `/tasks/{task_id}` | owner | Delete task. |
| GET | `/projects/{project_id}/tasks/search` | owner | Search by text / ref / filters. |
| POST | `/tasks/{task_id}/comments` | owner | Add a comment. |

### Project Notes

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/projects/{project_slug_or_id}/notes` | owner | Fetch freeform project notes (markdown). |
| PUT | `/projects/{project_slug_or_id}/notes` | owner | Replace project notes. |

## Auth

All endpoints require `current_active_user` and project ownership (or team access via `get_project_with_access`).

## Related

- Models: `KanbanColumn`, `KanbanTask`, `KanbanComment`, `ProjectNotes` in [models.py](../../../orchestrator/app/models.py).
- Agent tool: [../agent/kanban-agent-tool.md](../agent/kanban-agent-tool.md).
