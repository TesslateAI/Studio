"""
Kanban Board Models

Provides a comprehensive project management system with kanban boards,
customizable columns, tasks with rich metadata, and backlog management.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
import uuid
from .database import Base


class KanbanBoard(Base):
    """
    Kanban board for a project. Each project can have one board.
    """
    __tablename__ = "kanban_boards"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True)
    name = Column(String, nullable=False, default="Project Board")
    description = Column(Text, nullable=True)

    # Board settings
    settings = Column(JSON, nullable=True)  # Custom settings: colors, automation rules, etc.

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    project = relationship("Project", back_populates="kanban_board")
    columns = relationship("KanbanColumn", back_populates="board", cascade="all, delete-orphan", order_by="KanbanColumn.position")
    tasks = relationship("KanbanTask", back_populates="board", cascade="all, delete-orphan")


class KanbanColumn(Base):
    """
    Columns in a kanban board (e.g., Backlog, To Do, In Progress, Done).
    Fully customizable - users can add/remove/reorder columns.
    """
    __tablename__ = "kanban_columns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    board_id = Column(UUID(as_uuid=True), ForeignKey("kanban_boards.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    position = Column(Integer, nullable=False)  # Order of columns (0, 1, 2, ...)

    # Column styling
    color = Column(String, nullable=True)  # Hex color or color name (e.g., "blue", "#3B82F6")
    icon = Column(String, nullable=True)  # Emoji or icon identifier

    # Column behavior
    is_backlog = Column(Boolean, default=False)  # Special backlog column
    is_completed = Column(Boolean, default=False)  # Tasks here are considered done
    task_limit = Column(Integer, nullable=True)  # WIP limit (null = no limit)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    board = relationship("KanbanBoard", back_populates="columns")
    tasks = relationship("KanbanTask", back_populates="column", cascade="all, delete-orphan", order_by="KanbanTask.position")


class KanbanTask(Base):
    """
    Individual task/issue in the kanban board.
    Rich metadata for comprehensive project tracking.
    """
    __tablename__ = "kanban_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    board_id = Column(UUID(as_uuid=True), ForeignKey("kanban_boards.id", ondelete="CASCADE"), nullable=False)
    column_id = Column(UUID(as_uuid=True), ForeignKey("kanban_columns.id", ondelete="CASCADE"), nullable=False)

    # Task content
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)  # Markdown supported
    position = Column(Integer, nullable=False)  # Order within column

    # Task metadata
    priority = Column(String, nullable=True)  # low, medium, high, critical
    status = Column(String, nullable=True)  # Custom status beyond column (e.g., "blocked", "review")
    task_type = Column(String, nullable=True)  # feature, bug, task, epic, story
    tags = Column(JSON, nullable=True)  # ["frontend", "api", "urgent"]

    # Task details
    assignee_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # Who's working on it
    reporter_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # Who created it
    estimate_hours = Column(Integer, nullable=True)  # Time estimate
    spent_hours = Column(Integer, nullable=True)  # Time tracked

    # Dates
    due_date = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Additional data
    custom_fields = Column(JSON, nullable=True)  # Extensible custom data
    attachments = Column(JSON, nullable=True)  # File references, links

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    board = relationship("KanbanBoard", back_populates="tasks")
    column = relationship("KanbanColumn", back_populates="tasks")
    assignee = relationship("User", foreign_keys=[assignee_id])
    reporter = relationship("User", foreign_keys=[reporter_id])
    comments = relationship("KanbanTaskComment", back_populates="task", cascade="all, delete-orphan", order_by="KanbanTaskComment.created_at")


class KanbanTaskComment(Base):
    """
    Comments on kanban tasks for collaboration.
    """
    __tablename__ = "kanban_task_comments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    task_id = Column(UUID(as_uuid=True), ForeignKey("kanban_tasks.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    content = Column(Text, nullable=False)  # Markdown supported

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    task = relationship("KanbanTask", back_populates="comments")
    user = relationship("User")


class ProjectNote(Base):
    """
    Rich text notes for projects (separate from kanban tasks).
    Uses TipTap editor format.
    """
    __tablename__ = "project_notes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True)

    content = Column(Text, nullable=True)  # TipTap JSON or HTML content
    content_format = Column(String, default="html")  # html, json, markdown

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    project = relationship("Project", back_populates="notes")
