"""
Kanban Board API Router

Provides comprehensive CRUD operations for kanban boards, columns, tasks, and comments.
Includes search, filtering, and project management features.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models import Project, User
from ..models_kanban import KanbanBoard, KanbanColumn, KanbanTask, KanbanTaskComment, ProjectNote
from ..users import current_active_user

router = APIRouter(prefix="/api/kanban", tags=["kanban"])


# ============================================================================
# Pydantic Schemas
# ============================================================================


class KanbanColumnCreate(BaseModel):
    name: str
    description: str | None = None
    color: str | None = None
    icon: str | None = None
    is_backlog: bool = False
    is_completed: bool = False
    task_limit: int | None = None


class KanbanColumnUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    color: str | None = None
    icon: str | None = None
    position: int | None = None
    is_backlog: bool | None = None
    is_completed: bool | None = None
    task_limit: int | None = None


class KanbanTaskCreate(BaseModel):
    column_id: UUID
    title: str
    description: str | None = None
    priority: str | None = None
    status: str | None = None
    task_type: str | None = None
    tags: list[str] | None = None
    assignee_id: UUID | None = None
    point_value: int | None = None
    estimate_hours: int | None = None
    due_date: datetime | None = None


class KanbanTaskUpdate(BaseModel):
    column_id: UUID | None = None
    title: str | None = None
    description: str | None = None
    position: int | None = None
    priority: str | None = None
    status: str | None = None
    task_type: str | None = None
    tags: list[str] | None = None
    assignee_id: UUID | None = None
    point_value: int | None = None
    estimate_hours: int | None = None
    spent_hours: int | None = None
    due_date: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class KanbanTaskMove(BaseModel):
    column_id: UUID
    position: int


class TaskCommentCreate(BaseModel):
    content: str


class ProjectNoteUpdate(BaseModel):
    content: str
    content_format: str = "html"


# ============================================================================
# Helper Functions
# ============================================================================


async def get_project_id_from_slug_or_id(
    project_slug_or_id: str, db: AsyncSession, current_user: User
) -> UUID:
    """Get project ID from slug or UUID string and verify ownership."""
    # Try to parse as UUID first
    try:
        project_id = UUID(project_slug_or_id)
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
    except ValueError:
        # Not a UUID, treat as slug
        result = await db.execute(select(Project).where(Project.slug == project_slug_or_id))
        project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Verify access via RBAC
    from ..permissions import Permission, get_project_with_access

    project, _role = await get_project_with_access(
        db, project_slug_or_id, current_user.id, Permission.KANBAN_VIEW
    )

    return project.id


async def get_board_with_auth(
    project_id: UUID, db: AsyncSession, current_user: User, create_if_missing: bool = True
) -> KanbanBoard:
    """Get kanban board for project with authorization check."""
    # Verify project access via RBAC
    from ..permissions import Permission, get_project_with_access

    project, _role = await get_project_with_access(
        db, str(project_id), current_user.id, Permission.KANBAN_VIEW
    )

    # Get or create board
    board_result = await db.execute(
        select(KanbanBoard)
        .where(KanbanBoard.project_id == project_id)
        .options(selectinload(KanbanBoard.columns).selectinload(KanbanColumn.tasks))
    )
    board = board_result.scalar_one_or_none()

    if not board and create_if_missing:
        try:
            board = KanbanBoard(project_id=project_id, name=f"{project.name} Board")
            db.add(board)
            await db.flush()

            default_columns = [
                {"name": "Backlog", "color": "gray", "icon": "📋", "is_backlog": True, "position": 0},
                {"name": "To Do", "color": "blue", "icon": "📝", "position": 1},
                {"name": "In Progress", "color": "orange", "icon": "🚧", "position": 2},
                {"name": "Review", "color": "purple", "icon": "👀", "position": 3},
                {"name": "Done", "color": "green", "icon": "✅", "is_completed": True, "position": 4},
            ]

            for col_data in default_columns:
                column = KanbanColumn(board_id=board.id, **col_data)
                db.add(column)

            await db.commit()
            await db.refresh(board)
        except IntegrityError:
            await db.rollback()
            board_result = await db.execute(
                select(KanbanBoard)
                .where(KanbanBoard.project_id == project_id)
                .options(selectinload(KanbanBoard.columns).selectinload(KanbanColumn.tasks))
            )
            board = board_result.scalar_one_or_none()

    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    return board


async def reorder_tasks_in_column(
    db: AsyncSession, column_id: UUID, exclude_task_id: UUID | None = None
):
    """Reorder tasks in a column to ensure sequential positions."""
    query = select(KanbanTask).where(KanbanTask.column_id == column_id)
    if exclude_task_id:
        query = query.where(KanbanTask.id != exclude_task_id)
    query = query.order_by(KanbanTask.position)

    result = await db.execute(query)
    tasks = result.scalars().all()

    for idx, task in enumerate(tasks):
        task.position = idx


# ============================================================================
# Board Endpoints
# ============================================================================


@router.get("/projects/{project_id}/board")
async def get_board(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Get complete kanban board with all columns and tasks."""
    resolved_project_id = await get_project_id_from_slug_or_id(project_id, db, current_user)
    board = await get_board_with_auth(resolved_project_id, db, current_user)

    # Load all relationships
    await db.refresh(board, ["columns"])
    for column in board.columns:
        await db.refresh(column, ["tasks"])
        for task in column.tasks:
            await db.refresh(task, ["assignee", "reporter"])

    return {
        "id": board.id,
        "project_id": board.project_id,
        "name": board.name,
        "description": board.description,
        "settings": board.settings,
        "columns": [
            {
                "id": col.id,
                "name": col.name,
                "description": col.description,
                "position": col.position,
                "color": col.color,
                "icon": col.icon,
                "is_backlog": col.is_backlog,
                "is_completed": col.is_completed,
                "task_limit": col.task_limit,
                "tasks": [
                    {
                        "id": task.id,
                        "title": task.title,
                        "description": task.description,
                        "position": task.position,
                        "priority": task.priority,
                        "status": task.status,
                        "task_type": task.task_type,
                        "tags": task.tags,
                        "assignee": {
                            "id": task.assignee.id,
                            "name": task.assignee.name,
                            "username": task.assignee.username,
                        }
                        if task.assignee
                        else None,
                        "reporter": {
                            "id": task.reporter.id,
                            "name": task.reporter.name,
                            "username": task.reporter.username,
                        }
                        if task.reporter
                        else None,
                        "point_value": task.point_value,
                        "estimate_hours": task.estimate_hours,
                        "spent_hours": task.spent_hours,
                        "due_date": task.due_date.isoformat() if task.due_date else None,
                        "started_at": task.started_at.isoformat() if task.started_at else None,
                        "completed_at": task.completed_at.isoformat()
                        if task.completed_at
                        else None,
                        "created_at": task.created_at.isoformat(),
                        "updated_at": task.updated_at.isoformat(),
                    }
                    for task in sorted(col.tasks, key=lambda t: t.position)
                ],
            }
            for col in sorted(board.columns, key=lambda c: c.position)
        ],
        "created_at": board.created_at.isoformat(),
        "updated_at": board.updated_at.isoformat(),
    }


# ============================================================================
# Column Endpoints
# ============================================================================


@router.post("/projects/{project_id}/columns")
async def create_column(
    project_id: str,
    column_data: KanbanColumnCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Create a new column in the board."""
    resolved_project_id = await get_project_id_from_slug_or_id(project_id, db, current_user)
    board = await get_board_with_auth(resolved_project_id, db, current_user)

    # Get max position
    result = await db.execute(
        select(func.max(KanbanColumn.position)).where(KanbanColumn.board_id == board.id)
    )
    max_position = result.scalar() or -1

    column = KanbanColumn(board_id=board.id, position=max_position + 1, **column_data.dict())
    db.add(column)
    await db.commit()
    await db.refresh(column)

    return {"id": column.id, "message": "Column created successfully"}


@router.patch("/columns/{column_id}")
async def update_column(
    column_id: UUID,
    column_data: KanbanColumnUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Update a column."""
    result = await db.execute(select(KanbanColumn).where(KanbanColumn.id == column_id))
    column = result.scalar_one_or_none()
    if not column:
        raise HTTPException(status_code=404, detail="Column not found")

    # Verify ownership
    board_result = await db.execute(select(KanbanBoard).where(KanbanBoard.id == column.board_id))
    board = board_result.scalar_one()
    await get_board_with_auth(board.project_id, db, current_user, create_if_missing=False)

    # Update fields
    for field, value in column_data.dict(exclude_unset=True).items():
        setattr(column, field, value)

    await db.commit()
    return {"message": "Column updated successfully"}


@router.delete("/columns/{column_id}")
async def delete_column(
    column_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Delete a column and all its tasks."""
    result = await db.execute(select(KanbanColumn).where(KanbanColumn.id == column_id))
    column = result.scalar_one_or_none()
    if not column:
        raise HTTPException(status_code=404, detail="Column not found")

    # Verify ownership
    board_result = await db.execute(select(KanbanBoard).where(KanbanBoard.id == column.board_id))
    board = board_result.scalar_one()
    await get_board_with_auth(board.project_id, db, current_user, create_if_missing=False)

    await db.delete(column)
    await db.commit()
    return {"message": "Column deleted successfully"}


# ============================================================================
# Task Endpoints
# ============================================================================


@router.post("/projects/{project_id}/tasks")
async def create_task(
    project_id: str,
    task_data: KanbanTaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Create a new task in a column."""
    resolved_project_id = await get_project_id_from_slug_or_id(project_id, db, current_user)
    board = await get_board_with_auth(resolved_project_id, db, current_user)

    # Verify column belongs to board
    column_result = await db.execute(
        select(KanbanColumn).where(
            KanbanColumn.id == task_data.column_id, KanbanColumn.board_id == board.id
        )
    )
    if not column_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Invalid column")

    # Get max position in column
    result = await db.execute(
        select(func.max(KanbanTask.position)).where(KanbanTask.column_id == task_data.column_id)
    )
    max_position = result.scalar() or -1

    task = KanbanTask(
        board_id=board.id,
        position=max_position + 1,
        reporter_id=current_user.id,
        **task_data.dict(),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    return {"id": task.id, "message": "Task created successfully"}


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Get task details with comments."""
    result = await db.execute(
        select(KanbanTask)
        .where(KanbanTask.id == task_id)
        .options(
            selectinload(KanbanTask.assignee),
            selectinload(KanbanTask.reporter),
            selectinload(KanbanTask.comments).selectinload(KanbanTaskComment.user),
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Verify ownership
    board_result = await db.execute(select(KanbanBoard).where(KanbanBoard.id == task.board_id))
    board = board_result.scalar_one()
    await get_board_with_auth(board.project_id, db, current_user, create_if_missing=False)

    return {
        "id": task.id,
        "board_id": task.board_id,
        "column_id": task.column_id,
        "title": task.title,
        "description": task.description,
        "position": task.position,
        "priority": task.priority,
        "status": task.status,
        "task_type": task.task_type,
        "tags": task.tags,
        "assignee": {
            "id": task.assignee.id,
            "name": task.assignee.name,
            "username": task.assignee.username,
        }
        if task.assignee
        else None,
        "reporter": {
            "id": task.reporter.id,
            "name": task.reporter.name,
            "username": task.reporter.username,
        }
        if task.reporter
        else None,
        "point_value": task.point_value,
        "estimate_hours": task.estimate_hours,
        "spent_hours": task.spent_hours,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "attachments": task.attachments,
        "custom_fields": task.custom_fields,
        "comments": [
            {
                "id": comment.id,
                "content": comment.content,
                "user": {
                    "id": comment.user.id,
                    "name": comment.user.name,
                    "username": comment.user.username,
                },
                "created_at": comment.created_at.isoformat(),
                "updated_at": comment.updated_at.isoformat(),
            }
            for comment in task.comments
        ],
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: UUID,
    task_data: KanbanTaskUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Update a task."""
    result = await db.execute(select(KanbanTask).where(KanbanTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Verify ownership
    board_result = await db.execute(select(KanbanBoard).where(KanbanBoard.id == task.board_id))
    board = board_result.scalar_one()
    await get_board_with_auth(board.project_id, db, current_user, create_if_missing=False)

    # Handle column change
    if task_data.column_id is not None and task_data.column_id != task.column_id:
        # Verify new column belongs to same board
        column_result = await db.execute(
            select(KanbanColumn).where(
                KanbanColumn.id == task_data.column_id, KanbanColumn.board_id == board.id
            )
        )
        if not column_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Invalid column")

        # Reorder old column
        await reorder_tasks_in_column(db, task.column_id, exclude_task_id=task.id)

        # Get max position in new column
        result = await db.execute(
            select(func.max(KanbanTask.position)).where(KanbanTask.column_id == task_data.column_id)
        )
        max_position = result.scalar() or -1
        task.position = max_position + 1

    # Update fields
    for field, value in task_data.dict(exclude_unset=True).items():
        if (
            field != "position" or task_data.column_id is None
        ):  # Handle position separately for moves
            setattr(task, field, value)

    task.updated_at = func.now()
    await db.commit()
    return {"message": "Task updated successfully"}


@router.post("/tasks/{task_id}/move")
async def move_task(
    task_id: UUID,
    move_data: KanbanTaskMove,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Move a task to a different column and/or position."""
    result = await db.execute(select(KanbanTask).where(KanbanTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Verify ownership
    board_result = await db.execute(select(KanbanBoard).where(KanbanBoard.id == task.board_id))
    board = board_result.scalar_one()
    await get_board_with_auth(board.project_id, db, current_user, create_if_missing=False)

    old_column_id = task.column_id
    new_column_id = move_data.column_id

    # Verify new column
    column_result = await db.execute(
        select(KanbanColumn).where(
            KanbanColumn.id == new_column_id, KanbanColumn.board_id == board.id
        )
    )
    if not column_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Invalid column")

    # Remove from old column
    await reorder_tasks_in_column(db, old_column_id, exclude_task_id=task.id)

    # Insert into new position in new column
    if old_column_id != new_column_id:
        # Moving to different column
        result = await db.execute(
            select(KanbanTask)
            .where(KanbanTask.column_id == new_column_id, KanbanTask.position >= move_data.position)
            .order_by(KanbanTask.position.desc())
        )
        tasks_to_shift = result.scalars().all()
        for t in tasks_to_shift:
            t.position += 1

    task.column_id = new_column_id
    task.position = move_data.position
    task.updated_at = func.now()

    await db.commit()
    return {"message": "Task moved successfully"}


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Delete a task."""
    result = await db.execute(select(KanbanTask).where(KanbanTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Verify ownership
    board_result = await db.execute(select(KanbanBoard).where(KanbanBoard.id == task.board_id))
    board = board_result.scalar_one()
    await get_board_with_auth(board.project_id, db, current_user, create_if_missing=False)

    column_id = task.column_id
    await db.delete(task)
    await reorder_tasks_in_column(db, column_id)
    await db.commit()

    return {"message": "Task deleted successfully"}


@router.get("/projects/{project_id}/tasks/search")
async def search_tasks(
    project_id: str,
    q: str | None = Query(None, description="Search query"),
    priority: str | None = Query(None),
    task_type: str | None = Query(None),
    assignee_id: UUID | None = Query(None),
    tags: str | None = Query(None, description="Comma-separated tags"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Search and filter tasks."""
    resolved_project_id = await get_project_id_from_slug_or_id(project_id, db, current_user)
    board = await get_board_with_auth(
        resolved_project_id, db, current_user, create_if_missing=False
    )

    query = select(KanbanTask).where(KanbanTask.board_id == board.id)

    # Text search
    if q:
        query = query.where(
            or_(KanbanTask.title.ilike(f"%{q}%"), KanbanTask.description.ilike(f"%{q}%"))
        )

    # Filters
    if priority:
        query = query.where(KanbanTask.priority == priority)
    if task_type:
        query = query.where(KanbanTask.task_type == task_type)
    if assignee_id:
        query = query.where(KanbanTask.assignee_id == assignee_id)
    if tags:
        tag_list = [t.strip() for t in tags.split(",")]
        # Search for any of the tags in the JSONB array
        query = query.where(KanbanTask.tags.overlap(tag_list))

    result = await db.execute(query.options(selectinload(KanbanTask.assignee)))
    tasks = result.scalars().all()

    return {
        "tasks": [
            {
                "id": task.id,
                "column_id": task.column_id,
                "title": task.title,
                "description": task.description,
                "priority": task.priority,
                "task_type": task.task_type,
                "tags": task.tags,
                "point_value": task.point_value,
                "assignee": {"id": task.assignee.id, "name": task.assignee.name}
                if task.assignee
                else None,
                "created_at": task.created_at.isoformat(),
            }
            for task in tasks
        ],
        "total": len(tasks),
    }


# ============================================================================
# Comments Endpoints
# ============================================================================


@router.post("/tasks/{task_id}/comments")
async def add_comment(
    task_id: UUID,
    comment_data: TaskCommentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Add a comment to a task."""
    result = await db.execute(select(KanbanTask).where(KanbanTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Verify ownership
    board_result = await db.execute(select(KanbanBoard).where(KanbanBoard.id == task.board_id))
    board = board_result.scalar_one()
    await get_board_with_auth(board.project_id, db, current_user, create_if_missing=False)

    comment = KanbanTaskComment(
        task_id=task_id, user_id=current_user.id, content=comment_data.content
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    return {"id": comment.id, "message": "Comment added successfully"}


# ============================================================================
# Notes Endpoints
# ============================================================================


@router.get("/projects/{project_slug_or_id}/notes")
async def get_notes(
    project_slug_or_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Get project notes."""
    project_id = await get_project_id_from_slug_or_id(project_slug_or_id, db, current_user)

    result = await db.execute(select(ProjectNote).where(ProjectNote.project_id == project_id))
    notes = result.scalar_one_or_none()

    if not notes:
        # Create empty notes
        notes = ProjectNote(
            project_id=project_id,
            content="<p>Start writing your project notes...</p>",
            content_format="html",
        )
        db.add(notes)
        await db.commit()
        await db.refresh(notes)

    return {
        "id": notes.id,
        "content": notes.content,
        "content_format": notes.content_format,
        "updated_at": notes.updated_at.isoformat(),
    }


@router.put("/projects/{project_slug_or_id}/notes")
async def update_notes(
    project_slug_or_id: str,
    notes_data: ProjectNoteUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Update project notes."""
    project_id = await get_project_id_from_slug_or_id(project_slug_or_id, db, current_user)

    result = await db.execute(select(ProjectNote).where(ProjectNote.project_id == project_id))
    notes = result.scalar_one_or_none()

    if not notes:
        notes = ProjectNote(project_id=project_id)
        db.add(notes)

    notes.content = notes_data.content
    notes.content_format = notes_data.content_format
    notes.updated_at = func.now()

    await db.commit()
    return {"message": "Notes updated successfully"}
