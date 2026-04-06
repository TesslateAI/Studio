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
      ├─ search_tasks      → Search/filter across board (by column, text, priority, etc.)
      ├─ add_comment       → Comment on a task
      ├─ create_column     → Add a new column
      ├─ update_column     → Modify column properties
      └─> delete_column    → Remove a column
```

## Task Reference IDs (TSK-NNNN)

Every task gets a human-readable reference number auto-incremented per board:
- Format: `TSK-0001`, `TSK-0002`, etc.
- Stored as `KanbanTask.ref_number` (integer) with `KanbanBoard.task_counter` tracking the next value
- The agent can use refs in any action: `"task_id": "TSK-0003"` or `"ref": "0003"`
- `_fetch_task()` resolves UUID, `TSK-NNNN`, `0001`, `#1`, or plain `1`
- All tool output uses ref labels instead of UUIDs for readability

## Key Design Decisions

### Column Resolution by Name
The agent resolves columns by **name** (case-insensitive) with UUID fallback. This means the agent can say `"column": "In Progress"` without needing to call `get_board` first to discover column IDs.

### Direct Database Access
The tool operates directly on kanban database models (`KanbanBoard`, `KanbanColumn`, `KanbanTask`, `KanbanTaskComment`) via the `db` AsyncSession from agent context. It does NOT call HTTP endpoints.

### Not a Dangerous Tool
The kanban tool only reads/writes the project's own board data. It cannot leak data externally, modify files, or run commands. It is NOT in `DANGEROUS_TOOLS` and does not require approval in "ask" mode.

### Reporter = Project Owner
When the agent creates a task, `reporter_id` is set to `user_id` from context (the project owner who initiated the agent session).

### Output Format
All tool results embed actionable data inline in the `message` field (the only field reliably rendered by `_format_tool_results()`). The agent sees human-readable text with refs, not nested JSON:

```
get_board:     "Board: 6 task(s), 29 pts\n[To Do] (2 tasks)\n  - TSK-0001 Setup project (high) [3pts]"
create_task:   "Created TSK-0007 'Fix auth' in column 'To Do'"
search_tasks:  "Found 4 task(s):\n  - TSK-0001 Setup project (high) [3pts] column=Backlog"
```

### Auto-Refresh
When the agent completes a kanban tool call, `ChatContainer` dispatches a `kanban-updated` CustomEvent. `KanbanPanel` listens for this event and reloads the board with a 300ms debounce. Only successful tool results trigger the refresh.

## Actions Reference

| Action | Required Params | Optional Params | Description |
|--------|----------------|-----------------|-------------|
| `get_board` | — | — | Returns full board: columns with tasks, point totals |
| `create_task` | `title`, `column` | `description`, `priority`, `task_type`, `tags`, `assignee_id`, `point_value`, `estimate_hours`, `due_date`, `status` | Create task in column (by name or UUID) |
| `update_task` | `task_id` or `ref` | Any task field | Update title, description, priority, point_value, assignee, tags, etc. |
| `move_task` | `task_id` or `ref`, `column` | `position` | Move task to target column, optional position |
| `delete_task` | `task_id` or `ref` | — | Delete task, reorder remaining tasks in column |
| `search_tasks` | At least one filter | `query`, `column`, `priority`, `task_type`, `assignee_id`, `tags` | Search by text, column, priority, type, assignee, or tags |
| `add_comment` | `task_id` or `ref`, `content` | — | Add markdown comment to a task |
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

## Database Models

| Model | Table | Key Fields |
|-------|-------|------------|
| `KanbanBoard` | `kanban_boards` | `project_id` (unique), `task_counter` |
| `KanbanColumn` | `kanban_columns` | `board_id`, `name`, `position`, `is_backlog`, `is_completed` |
| `KanbanTask` | `kanban_tasks` | `board_id`, `column_id`, `ref_number`, `title`, `point_value`, `priority` |
| `KanbanTaskComment` | `kanban_task_comments` | `task_id`, `user_id`, `content` |

## Migrations

| Migration | Description |
|-----------|-------------|
| `0037_add_kanban_point_value` | Adds `point_value` integer to `kanban_tasks` |
| `0038_add_kanban_task_ref_number` | Adds `task_counter` to boards, `ref_number` to tasks, backfills existing |

## Files

| File | Role |
|------|------|
| `orchestrator/app/agent/tools/project_ops/kanban.py` | Tool implementation (executor + registration) |
| `orchestrator/app/agent/tools/project_ops/__init__.py` | Registration wiring |
| `orchestrator/app/models_kanban.py` | Database models |
| `orchestrator/app/routers/kanban.py` | REST API endpoints (used by frontend) |
| `app/src/components/panels/KanbanPanel.tsx` | React UI for the board |
| `app/src/components/chat/ChatContainer.tsx` | Dispatches kanban-updated event |

## Tests

| Suite | Count | Location |
|-------|-------|----------|
| Unit | 36 | `orchestrator/tests/agent/unit/test_kanban_tool.py` |
| Integration | 22 | `orchestrator/tests/agent/integration/test_kanban_integration.py` |
| Frontend | 9 | `app/src/components/panels/KanbanPanel.test.tsx` |

## Related Contexts

- [Agent Tools CLAUDE.md](tools/CLAUDE.md) — Tool registration patterns, output formatters
- [Project Control Tool](tools/project-control.md) — Same action-dispatch pattern
- [Kanban Router](../routers/CLAUDE.md) — REST API counterpart
