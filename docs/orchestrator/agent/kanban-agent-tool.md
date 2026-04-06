# Kanban Agent Tool

## Purpose

The `kanban` agent tool gives the AI agent first-class access to the project's onboard kanban board. Inspired by Linear's agent-first approach, the agent becomes a direct participant in project management — creating issues, moving tasks, reassigning work, adding comments, and managing the board structure.

## Architecture

The tool follows the **action-dispatch pattern** (same as `project_control.py`): a single tool named `kanban` with an `action` parameter that routes to sub-handlers.

```
Agent calls kanban tool
  └─> kanban_executor(params, context)
      ├─ get_board         → Full board state with columns & tasks
      ├─ create_task       → New task in a column (by name or UUID)
      ├─ update_task       → Update any task fields
      ├─ move_task         → Move task between columns
      ├─ delete_task       → Remove a task
      ├─ search_tasks      → Search/filter across board
      ├─ add_comment       → Comment on a task
      ├─ create_column     → Add a new column
      ├─ update_column     → Modify column properties
      └─> delete_column    → Remove a column
```

## Key Design Decisions

### Column Resolution by Name
The agent resolves columns by **name** (case-insensitive) with UUID fallback. This means the agent can say `"column": "In Progress"` without needing to call `get_board` first to discover column IDs.

### Direct Database Access
The tool operates directly on kanban database models (`KanbanBoard`, `KanbanColumn`, `KanbanTask`, `KanbanTaskComment`) via the `db` AsyncSession from agent context. It does NOT call HTTP endpoints.

### Not a Dangerous Tool
The kanban tool only reads/writes the project's own board data. It cannot leak data externally, modify files, or run commands. It is NOT in `DANGEROUS_TOOLS` and does not require approval in "ask" mode.

### Reporter = Project Owner
When the agent creates a task, `reporter_id` is set to `user_id` from context (the project owner who initiated the agent session).

## Actions Reference

| Action | Required Params | Optional Params | Description |
|--------|----------------|-----------------|-------------|
| `get_board` | — | — | Returns full board: columns with tasks, point totals |
| `create_task` | `title`, `column` | `description`, `priority`, `task_type`, `tags`, `assignee_id`, `point_value`, `estimate_hours`, `due_date`, `status` | Create task in column (by name or UUID) |
| `update_task` | `task_id` | Any task field | Update title, description, priority, point_value, assignee, tags, etc. |
| `move_task` | `task_id`, `column` | `position` | Move task to target column, optional position |
| `delete_task` | `task_id` | — | Delete task, reorder remaining tasks in column |
| `search_tasks` | At least one filter | `query`, `priority`, `task_type`, `assignee_id`, `tags` | Search by text, priority, type, assignee, or tags |
| `add_comment` | `task_id`, `content` | — | Add markdown comment to a task |
| `create_column` | `title` | `description`, `color`, `icon`, `is_backlog`, `is_completed`, `task_limit` | Create a new board column |
| `update_column` | `column_id` | Any column field | Update column properties |
| `delete_column` | `column_id` | — | Delete column and all its tasks |

## Task Fields

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Task title (required on create) |
| `description` | string | Markdown description |
| `priority` | enum | `low`, `medium`, `high`, `critical` |
| `task_type` | enum | `feature`, `bug`, `task`, `epic`, `story` |
| `tags` | string[] | Labels like `["frontend", "api"]` |
| `assignee_id` | UUID | User assigned to the task |
| `point_value` | integer | Story points (e.g., 1, 2, 3, 5, 8, 13, 21) |
| `estimate_hours` | integer | Time estimate in hours |
| `due_date` | ISO 8601 | Deadline |
| `status` | string | Custom status (e.g., `"blocked"`, `"review"`) |

## Files

| File | Role |
|------|------|
| `orchestrator/app/agent/tools/project_ops/kanban.py` | Tool implementation (executor + registration) |
| `orchestrator/app/agent/tools/project_ops/__init__.py` | Registration wiring |
| `orchestrator/app/models_kanban.py` | Database models (KanbanBoard, KanbanColumn, KanbanTask, KanbanTaskComment) |
| `orchestrator/app/routers/kanban.py` | REST API endpoints (used by frontend, not by the tool) |
| `app/src/components/panels/KanbanPanel.tsx` | React UI for the board |

## Related Contexts

- [Agent Tools CLAUDE.md](tools/CLAUDE.md) — Tool registration patterns, output formatters
- [Project Control Tool](tools/project-control.md) — Same action-dispatch pattern
- [Kanban Router](../routers/CLAUDE.md) — REST API counterpart
