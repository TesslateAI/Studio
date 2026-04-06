"""
Kanban Tool — board, column, task, and comment management from agent context.

Gives the AI agent first-class access to the project's onboard kanban board.
The agent can create issues, move tasks between columns, reassign work, add
comments, and manage the board structure.

Actions:
  get_board      — view full board state with columns and tasks
  create_task    — create a new task in a column (by name or UUID)
  update_task    — update any task fields
  move_task      — move task between columns
  delete_task    — remove a task
  search_tasks   — search/filter across the board
  add_comment    — comment on a task
  create_column  — add a new column
  update_column  — modify column properties
  delete_column  — remove a column and its tasks
"""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID as _UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)

# Default columns created when a board is auto-provisioned.
_DEFAULT_COLUMNS = [
    {"name": "Backlog", "color": "gray", "icon": "📋", "is_backlog": True, "position": 0},
    {"name": "To Do", "color": "blue", "icon": "📝", "position": 1},
    {"name": "In Progress", "color": "orange", "icon": "🚧", "position": 2},
    {"name": "Review", "color": "purple", "icon": "👀", "position": 3},
    {"name": "Done", "color": "green", "icon": "✅", "is_completed": True, "position": 4},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_or_create_board(db, project_id):
    """Return the KanbanBoard for *project_id*, creating one if absent."""
    from ....models_kanban import KanbanBoard, KanbanColumn

    result = await db.execute(
        select(KanbanBoard)
        .where(KanbanBoard.project_id == project_id)
        .options(selectinload(KanbanBoard.columns).selectinload(KanbanColumn.tasks))
    )
    board = result.scalar_one_or_none()

    if board is not None:
        return board

    # Auto-create board with default columns.
    try:
        board = KanbanBoard(project_id=project_id, name="Project Board")
        db.add(board)
        await db.flush()

        for col_data in _DEFAULT_COLUMNS:
            db.add(KanbanColumn(board_id=board.id, **col_data))

        await db.commit()
        await db.refresh(board)
    except IntegrityError:
        await db.rollback()
        result = await db.execute(
            select(KanbanBoard)
            .where(KanbanBoard.project_id == project_id)
            .options(selectinload(KanbanBoard.columns).selectinload(KanbanColumn.tasks))
        )
        board = result.scalar_one_or_none()

    return board


async def _resolve_column(db, board_id, column_ref: str):
    """Resolve a column by UUID or case-insensitive name.

    Returns the first matching KanbanColumn or ``None``.
    """
    from ....models_kanban import KanbanColumn

    # Try UUID first.
    try:
        col_id = _UUID(column_ref)
        result = await db.execute(
            select(KanbanColumn).where(
                KanbanColumn.id == col_id,
                KanbanColumn.board_id == board_id,
            )
        )
        return result.scalar_one_or_none()
    except ValueError:
        pass

    # Fall back to case-insensitive name match.
    result = await db.execute(
        select(KanbanColumn).where(
            KanbanColumn.board_id == board_id,
            func.lower(KanbanColumn.name) == column_ref.strip().lower(),
        )
    )
    return result.scalars().first()


async def _fetch_task(db, task_id: str, board_id=None):
    """Fetch a KanbanTask by UUID, ref number, or ref label (e.g. 'TSK-0001').

    Tries UUID first, then parses as a reference number within the board.
    """
    from ....models_kanban import KanbanTask

    # Try UUID first.
    try:
        tid = _UUID(task_id)
        result = await db.execute(select(KanbanTask).where(KanbanTask.id == tid))
        task = result.scalar_one_or_none()
        if task:
            return task
    except ValueError:
        pass

    # Parse reference number: "TSK-0001", "0001", "1", "#1", "#0001"
    ref_str = task_id.strip().upper().replace("TSK-", "").lstrip("#")
    try:
        ref_num = int(ref_str)
    except ValueError:
        return None

    query = select(KanbanTask).where(KanbanTask.ref_number == ref_num)
    if board_id:
        query = query.where(KanbanTask.board_id == board_id)
    result = await db.execute(query)
    return result.scalars().first()


async def _next_ref_number(db, board):
    """Atomically increment the board's task counter and return the new value."""
    board.task_counter = (board.task_counter or 0) + 1
    await db.flush()
    return board.task_counter


def _ref_label(task) -> str:
    """Format a task's reference number as TSK-NNNN."""
    if task.ref_number:
        return f"TSK-{task.ref_number:04d}"
    return str(task.id)[:8]


async def _resolve_task_param(params, db, board_id=None):
    """Resolve a task from 'task_id' or 'ref' param. Returns (task, error_output)."""
    task_id = params.get("task_id") or params.get("ref")
    if not task_id:
        return None, error_output(
            message="'task_id' or 'ref' is required (e.g. 'TSK-0001' or UUID)",
            suggestion="Use get_board to see task reference numbers",
        )
    task = await _fetch_task(db, str(task_id), board_id=board_id)
    if not task:
        return None, error_output(message=f"Task '{task_id}' not found")
    return task, None


async def _reorder_tasks_in_column(db, column_id, exclude_task_id=None):
    """Reorder tasks in a column to ensure sequential positions."""
    from ....models_kanban import KanbanTask

    query = select(KanbanTask).where(KanbanTask.column_id == column_id)
    if exclude_task_id:
        query = query.where(KanbanTask.id != exclude_task_id)
    query = query.order_by(KanbanTask.position)

    result = await db.execute(query)
    for idx, task in enumerate(result.scalars().all()):
        task.position = idx


async def _max_position(db, column_id):
    """Return the current max position in a column, or -1 if empty."""
    from ....models_kanban import KanbanTask

    result = await db.execute(
        select(func.max(KanbanTask.position)).where(KanbanTask.column_id == column_id)
    )
    return result.scalar() or -1


def _serialize_task(task) -> dict[str, Any]:
    """Convert a KanbanTask to a JSON-safe dict."""
    return {
        "id": str(task.id),
        "column_id": str(task.column_id),
        "title": task.title,
        "description": task.description,
        "position": task.position,
        "priority": task.priority,
        "status": task.status,
        "task_type": task.task_type,
        "tags": task.tags,
        "assignee_id": str(task.assignee_id) if task.assignee_id else None,
        "reporter_id": str(task.reporter_id) if task.reporter_id else None,
        "point_value": task.point_value,
        "estimate_hours": task.estimate_hours,
        "spent_hours": task.spent_hours,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def _serialize_column(col) -> dict[str, Any]:
    """Convert a KanbanColumn to a JSON-safe dict (without tasks)."""
    return {
        "id": str(col.id),
        "name": col.name,
        "description": col.description,
        "position": col.position,
        "color": col.color,
        "icon": col.icon,
        "is_backlog": col.is_backlog,
        "is_completed": col.is_completed,
        "task_limit": col.task_limit,
    }


# ---------------------------------------------------------------------------
# Action implementations
# ---------------------------------------------------------------------------


async def _action_get_board(context: dict[str, Any]) -> dict[str, Any]:
    db = context["db"]
    project_id = context["project_id"]

    board = await _get_or_create_board(db, project_id)
    if not board:
        return error_output(message="Could not load or create kanban board")

    # Reload with all relationships.
    from ....models_kanban import KanbanBoard, KanbanColumn

    result = await db.execute(
        select(KanbanBoard)
        .where(KanbanBoard.id == board.id)
        .options(selectinload(KanbanBoard.columns).selectinload(KanbanColumn.tasks))
    )
    board = result.scalar_one()

    total_points = 0
    total_tasks = 0
    lines = []
    for col in sorted(board.columns, key=lambda c: c.position):
        tasks_sorted = sorted(col.tasks, key=lambda t: t.position)
        col_points = sum(t.point_value or 0 for t in tasks_sorted)
        total_points += col_points
        total_tasks += len(tasks_sorted)
        lines.append(f"\n[{col.name}] ({len(tasks_sorted)} tasks, {col_points} pts)")
        for t in tasks_sorted:
            ref = _ref_label(t)
            pts = f" [{t.point_value}pts]" if t.point_value else ""
            pri = f" ({t.priority})" if t.priority else ""
            lines.append(f"  - {ref} {t.title}{pri}{pts}")

    summary = f"Board: {total_tasks} task(s), {total_points} pts\n" + "\n".join(lines)

    return success_output(message=summary)


async def _action_create_task(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    db = context["db"]
    project_id = context["project_id"]
    user_id = context["user_id"]

    title = params.get("title")
    column_ref = params.get("column")
    if not title:
        return error_output(
            message="'title' is required for create_task",
            suggestion="Provide a title for the new task",
        )
    if not column_ref:
        return error_output(
            message="'column' is required for create_task",
            suggestion="Specify a column name (e.g. 'To Do') or column UUID",
        )

    board = await _get_or_create_board(db, project_id)
    if not board:
        return error_output(message="Could not load or create kanban board")

    column = await _resolve_column(db, board.id, column_ref)
    if not column:
        return error_output(
            message=f"Column '{column_ref}' not found",
            suggestion="Use get_board to see available columns",
        )

    from ....models_kanban import KanbanTask

    position = await _max_position(db, column.id) + 1
    ref_num = await _next_ref_number(db, board)

    # Parse due_date if provided as string.
    due_date = params.get("due_date")
    if isinstance(due_date, str):
        try:
            due_date = datetime.fromisoformat(due_date)
        except ValueError:
            due_date = None

    task = KanbanTask(
        board_id=board.id,
        column_id=column.id,
        ref_number=ref_num,
        title=title,
        description=params.get("description"),
        position=position,
        priority=params.get("priority"),
        status=params.get("status"),
        task_type=params.get("task_type"),
        tags=params.get("tags"),
        assignee_id=params.get("assignee_id"),
        reporter_id=str(user_id),
        point_value=params.get("point_value"),
        estimate_hours=params.get("estimate_hours"),
        due_date=due_date,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    ref = _ref_label(task)
    return success_output(
        message=f"Created {ref} '{title}' in column '{column.name}'",
    )


async def _action_update_task(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    db = context["db"]

    task, err = await _resolve_task_param(params, db)
    if err:
        return err

    updatable = [
        "title", "description", "priority", "status", "task_type",
        "tags", "assignee_id", "point_value", "estimate_hours",
        "spent_hours", "due_date", "started_at", "completed_at",
    ]

    updated_fields = []
    for field in updatable:
        if field in params and params[field] is not None:
            value = params[field]
            # Parse date strings.
            if field in ("due_date", "started_at", "completed_at") and isinstance(value, str):
                try:
                    value = datetime.fromisoformat(value)
                except ValueError:
                    continue
            setattr(task, field, value)
            updated_fields.append(field)

    if not updated_fields:
        return error_output(
            message="No fields to update",
            suggestion="Provide at least one field to change (title, priority, point_value, etc.)",
        )

    await db.commit()
    await db.refresh(task)

    ref = _ref_label(task)
    return success_output(
        message=f"Updated {ref} '{task.title}' — changed: {', '.join(updated_fields)}",
    )


async def _action_move_task(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    db = context["db"]
    project_id = context["project_id"]

    column_ref = params.get("column")
    if not column_ref:
        return error_output(
            message="'column' is required for move_task",
            suggestion="Specify destination column name or UUID",
        )

    task, err = await _resolve_task_param(params, db)
    if err:
        return err

    board = await _get_or_create_board(db, project_id)
    if not board:
        return error_output(message="Could not load kanban board")

    target_column = await _resolve_column(db, board.id, column_ref)
    if not target_column:
        return error_output(
            message=f"Column '{column_ref}' not found",
            suggestion="Use get_board to see available columns",
        )

    old_column_id = task.column_id
    old_column_name = None

    # Get old column name for the message.
    from ....models_kanban import KanbanColumn

    old_col_result = await db.execute(
        select(KanbanColumn).where(KanbanColumn.id == old_column_id)
    )
    old_col = old_col_result.scalar_one_or_none()
    if old_col:
        old_column_name = old_col.name

    # Reorder old column (excluding this task).
    await _reorder_tasks_in_column(db, old_column_id, exclude_task_id=task.id)

    # Determine target position.
    position = params.get("position")
    if position is not None:
        # Shift existing tasks at or after the target position.
        from ....models_kanban import KanbanTask

        shift_result = await db.execute(
            select(KanbanTask)
            .where(
                KanbanTask.column_id == target_column.id,
                KanbanTask.position >= position,
            )
            .order_by(KanbanTask.position.desc())
        )
        for t in shift_result.scalars().all():
            t.position += 1
    else:
        position = await _max_position(db, target_column.id) + 1

    task.column_id = target_column.id
    task.position = position
    await db.commit()
    await db.refresh(task)

    ref = _ref_label(task)
    msg = f"Moved {ref} '{task.title}'"
    if old_column_name:
        msg += f" from '{old_column_name}'"
    msg += f" to '{target_column.name}'"

    return success_output(message=msg)


async def _action_delete_task(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    db = context["db"]

    task, err = await _resolve_task_param(params, db)
    if err:
        return err

    ref = _ref_label(task)
    title = task.title
    column_id = task.column_id
    await db.delete(task)
    await _reorder_tasks_in_column(db, column_id)
    await db.commit()

    return success_output(message=f"Deleted {ref} '{title}'")


async def _action_search_tasks(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    db = context["db"]
    project_id = context["project_id"]

    board = await _get_or_create_board(db, project_id)
    if not board:
        return error_output(message="Could not load kanban board")

    from ....models_kanban import KanbanColumn, KanbanTask

    # Resolve column filter first (by name or UUID).
    column_ref = params.get("column")
    target_column_id = None
    if column_ref:
        col = await _resolve_column(db, board.id, column_ref)
        if col:
            target_column_id = col.id
        else:
            return error_output(
                message=f"Column '{column_ref}' not found",
                suggestion="Use get_board to see available columns",
            )

    query = select(KanbanTask).where(KanbanTask.board_id == board.id)

    if target_column_id:
        query = query.where(KanbanTask.column_id == target_column_id)

    q = params.get("query")
    if q:
        query = query.where(
            or_(KanbanTask.title.ilike(f"%{q}%"), KanbanTask.description.ilike(f"%{q}%"))
        )

    priority = params.get("priority")
    if priority:
        query = query.where(KanbanTask.priority == priority)

    task_type = params.get("task_type")
    if task_type:
        query = query.where(KanbanTask.task_type == task_type)

    assignee_id = params.get("assignee_id")
    if assignee_id:
        query = query.where(KanbanTask.assignee_id == assignee_id)

    tags = params.get("tags")
    if tags:
        query = query.where(KanbanTask.tags.overlap(tags))

    result = await db.execute(query.order_by(KanbanTask.created_at.desc()))
    tasks = result.scalars().all()

    # Enrich with column names.
    col_ids = {t.column_id for t in tasks}
    col_map: dict[_UUID, str] = {}
    if col_ids:
        col_result = await db.execute(
            select(KanbanColumn).where(KanbanColumn.id.in_(col_ids))
        )
        for col in col_result.scalars().all():
            col_map[col.id] = col.name

    lines = []
    for t in tasks:
        ref = _ref_label(t)
        col_name = col_map.get(t.column_id, "Unknown")
        pts = f" [{t.point_value}pts]" if t.point_value else ""
        pri = f" ({t.priority})" if t.priority else ""
        lines.append(f"  - {ref} {t.title}{pri}{pts} column={col_name}")

    if lines:
        summary = f"Found {len(tasks)} task(s):\n" + "\n".join(lines)
    else:
        summary = "Found 0 task(s)"

    return success_output(message=summary)


async def _action_add_comment(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    db = context["db"]
    user_id = context["user_id"]

    content = params.get("content")
    if not content:
        return error_output(message="'content' is required for add_comment")

    task, err = await _resolve_task_param(params, db)
    if err:
        return err

    from ....models_kanban import KanbanTaskComment

    comment = KanbanTaskComment(
        task_id=task.id,
        user_id=str(user_id),
        content=content,
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    ref = _ref_label(task)
    return success_output(message=f"Added comment to {ref} '{task.title}'")


async def _action_create_column(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    db = context["db"]
    project_id = context["project_id"]

    title = params.get("title")
    if not title:
        return error_output(
            message="'title' is required for create_column",
            suggestion="Provide a name for the new column",
        )

    board = await _get_or_create_board(db, project_id)
    if not board:
        return error_output(message="Could not load kanban board")

    from ....models_kanban import KanbanColumn

    # Get max position.
    result = await db.execute(
        select(func.max(KanbanColumn.position)).where(KanbanColumn.board_id == board.id)
    )
    max_pos = result.scalar() or -1

    column = KanbanColumn(
        board_id=board.id,
        name=title,
        description=params.get("description"),
        position=max_pos + 1,
        color=params.get("color"),
        icon=params.get("icon"),
        is_backlog=params.get("is_backlog", False),
        is_completed=params.get("is_completed", False),
        task_limit=params.get("task_limit"),
    )
    db.add(column)
    await db.commit()
    await db.refresh(column)

    return success_output(
        message=f"Created column '{title}' at position {column.position} (id={column.id})",
    )


async def _action_update_column(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    db = context["db"]
    column_id = params.get("column_id")
    if not column_id:
        return error_output(message="'column_id' is required for update_column")

    from ....models_kanban import KanbanColumn

    try:
        cid = _UUID(column_id)
    except ValueError:
        return error_output(message=f"Invalid column UUID: '{column_id}'")

    result = await db.execute(select(KanbanColumn).where(KanbanColumn.id == cid))
    column = result.scalar_one_or_none()
    if not column:
        return error_output(message=f"Column '{column_id}' not found")

    updatable = ["title", "description", "color", "icon", "is_backlog", "is_completed", "task_limit"]
    updated_fields = []
    for field in updatable:
        if field in params and params[field] is not None:
            # Map 'title' param to 'name' model field.
            model_field = "name" if field == "title" else field
            setattr(column, model_field, params[field])
            updated_fields.append(field)

    if not updated_fields:
        return error_output(
            message="No fields to update",
            suggestion="Provide at least one field to change (title, color, task_limit, etc.)",
        )

    await db.commit()
    await db.refresh(column)

    return success_output(
        message=f"Updated column '{column.name}' (id={column.id}) — changed: {', '.join(updated_fields)}",
    )


async def _action_delete_column(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    db = context["db"]
    column_id = params.get("column_id")
    if not column_id:
        return error_output(message="'column_id' is required for delete_column")

    from ....models_kanban import KanbanColumn

    try:
        cid = _UUID(column_id)
    except ValueError:
        return error_output(message=f"Invalid column UUID: '{column_id}'")

    result = await db.execute(select(KanbanColumn).where(KanbanColumn.id == cid))
    column = result.scalar_one_or_none()
    if not column:
        return error_output(message=f"Column '{column_id}' not found")

    name = column.name
    await db.delete(column)
    await db.commit()

    return success_output(message=f"Deleted column '{name}' and all its tasks")


# ---------------------------------------------------------------------------
# Main executor
# ---------------------------------------------------------------------------

_ACTION_DISPATCH = {
    "get_board": lambda params, ctx: _action_get_board(ctx),
    "create_task": _action_create_task,
    "update_task": _action_update_task,
    "move_task": _action_move_task,
    "delete_task": _action_delete_task,
    "search_tasks": _action_search_tasks,
    "add_comment": _action_add_comment,
    "create_column": _action_create_column,
    "update_column": _action_update_column,
    "delete_column": _action_delete_column,
}

_ALL_ACTIONS = list(_ACTION_DISPATCH.keys())


async def kanban_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """
    Dispatch a kanban board action.

    Args:
        params: Must contain ``action``; additional fields vary per action.
        context: Execution context with db, user_id, project_id, etc.

    Returns:
        Standardised success/error output dict.
    """
    action = params.get("action")
    if not action:
        return error_output(
            message="'action' parameter is required",
            suggestion=f"Choose one of: {', '.join(_ALL_ACTIONS)}",
        )

    db = context.get("db")
    user_id = context.get("user_id")
    project_id = context.get("project_id")

    if not db or not user_id or not project_id:
        return error_output(
            message="Missing required context (db, user_id, or project_id)",
            suggestion="Ensure the tool is called within a valid project session",
        )

    handler = _ACTION_DISPATCH.get(action)
    if not handler:
        return error_output(
            message=f"Unknown action '{action}'",
            suggestion=f"Choose one of: {', '.join(_ALL_ACTIONS)}",
        )

    try:
        return await handler(params, context)
    except Exception as exc:
        logger.error("kanban action '%s' failed: %s", action, exc, exc_info=True)
        return error_output(
            message=f"Action '{action}' failed: {exc}",
            suggestion="Check the parameters and try again",
        )


# ---------------------------------------------------------------------------
# JSON Schema
# ---------------------------------------------------------------------------

parameters = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": _ALL_ACTIONS,
            "description": "The kanban action to perform.",
        },
        "task_id": {
            "type": "string",
            "description": "Task UUID or reference (e.g. 'TSK-0001', '0001', '1'). Required for update_task, move_task, delete_task, add_comment.",
        },
        "ref": {
            "type": "string",
            "description": "Task reference number (e.g. 'TSK-0001', '1', '0001'). Alternative to task_id.",
        },
        "column": {
            "type": "string",
            "description": (
                "Column name (e.g. 'In Progress') or UUID. "
                "Used by create_task, move_task, and search_tasks (filter by column)."
            ),
        },
        "title": {
            "type": "string",
            "description": "Task or column title. Required for create_task, create_column.",
        },
        "description": {
            "type": "string",
            "description": "Task or column description (markdown supported).",
        },
        "priority": {
            "type": "string",
            "enum": ["low", "medium", "high", "critical"],
            "description": "Task priority level.",
        },
        "task_type": {
            "type": "string",
            "enum": ["feature", "bug", "task", "epic", "story"],
            "description": "Type of task.",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Tags for the task (e.g. ['frontend', 'api']).",
        },
        "assignee_id": {
            "type": "string",
            "description": "UUID of user to assign the task to.",
        },
        "point_value": {
            "type": "integer",
            "description": "Story point estimate (e.g. 1, 2, 3, 5, 8, 13, 21).",
        },
        "estimate_hours": {
            "type": "integer",
            "description": "Estimated hours to complete the task.",
        },
        "due_date": {
            "type": "string",
            "description": "Due date in ISO 8601 format (e.g. '2026-04-15T00:00:00Z').",
        },
        "status": {
            "type": "string",
            "description": "Custom status string (e.g. 'blocked', 'review').",
        },
        "position": {
            "type": "integer",
            "description": "Position in column (0-indexed). Used by move_task.",
        },
        "column_id": {
            "type": "string",
            "description": "UUID of the column. Required for update_column, delete_column.",
        },
        "color": {
            "type": "string",
            "description": "Column color (hex or name, e.g. 'blue', '#3B82F6').",
        },
        "icon": {
            "type": "string",
            "description": "Column icon (emoji, e.g. '🚧').",
        },
        "is_backlog": {
            "type": "boolean",
            "description": "Whether this is a backlog column.",
        },
        "is_completed": {
            "type": "boolean",
            "description": "Whether tasks in this column are considered done.",
        },
        "task_limit": {
            "type": "integer",
            "description": "WIP limit for the column (null = no limit).",
        },
        "content": {
            "type": "string",
            "description": "Comment content (markdown). Required for add_comment.",
        },
        "query": {
            "type": "string",
            "description": "Search text to match against task titles and descriptions.",
        },
    },
    "required": ["action"],
}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_kanban_tools(registry):
    """Register the kanban tool."""
    registry.register(
        Tool(
            name="kanban",
            description=(
                "Manage the project's kanban board: create and move tasks, "
                "assign work, track story points, add comments, and organize "
                "columns. Use column names (e.g. 'To Do', 'In Progress') "
                "instead of UUIDs for convenience."
            ),
            category=ToolCategory.PROJECT,
            parameters=parameters,
            executor=kanban_executor,
            examples=[
                '{"tool_name": "kanban", "parameters": {"action": "get_board"}}',
                '{"tool_name": "kanban", "parameters": {"action": "create_task", "title": "Fix auth bug", "column": "To Do", "priority": "high", "point_value": 5}}',
                '{"tool_name": "kanban", "parameters": {"action": "move_task", "task_id": "TSK-0001", "column": "In Progress"}}',
                '{"tool_name": "kanban", "parameters": {"action": "update_task", "task_id": "TSK-0003", "point_value": 4}}',
                '{"tool_name": "kanban", "parameters": {"action": "add_comment", "task_id": "TSK-0005", "content": "Started working on this"}}',
                '{"tool_name": "kanban", "parameters": {"action": "search_tasks", "column": "In Progress"}}',
            ],
        )
    )
