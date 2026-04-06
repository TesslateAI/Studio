"""Add task reference numbers to kanban boards and tasks

Adds task_counter to kanban_boards (auto-incrementing counter) and
ref_number to kanban_tasks (human-readable reference like TSK-0001).
Backfills existing tasks with sequential ref_numbers per board.

Revision ID: 0038_kanban_task_ref
Revises: 0037_kanban_point_value
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038_kanban_task_ref"
down_revision: str | Sequence[str] | None = "0037_kanban_point_value"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add task_counter to boards
    op.add_column(
        "kanban_boards",
        sa.Column("task_counter", sa.Integer(), nullable=False, server_default="0"),
    )

    # Add ref_number to tasks
    op.add_column("kanban_tasks", sa.Column("ref_number", sa.Integer(), nullable=True))
    op.create_index("ix_kanban_tasks_ref_number", "kanban_tasks", ["ref_number"])

    # Backfill: assign sequential ref_numbers to existing tasks per board
    conn = op.get_bind()
    boards = conn.execute(sa.text("SELECT id FROM kanban_boards")).fetchall()
    for (board_id,) in boards:
        tasks = conn.execute(
            sa.text(
                "SELECT id FROM kanban_tasks WHERE board_id = :bid ORDER BY created_at"
            ),
            {"bid": board_id},
        ).fetchall()
        for idx, (task_id,) in enumerate(tasks, start=1):
            conn.execute(
                sa.text("UPDATE kanban_tasks SET ref_number = :ref WHERE id = :tid"),
                {"ref": idx, "tid": task_id},
            )
        # Set board counter to next value
        conn.execute(
            sa.text("UPDATE kanban_boards SET task_counter = :cnt WHERE id = :bid"),
            {"cnt": len(tasks), "bid": board_id},
        )


def downgrade() -> None:
    op.drop_index("ix_kanban_tasks_ref_number", table_name="kanban_tasks")
    op.drop_column("kanban_tasks", "ref_number")
    op.drop_column("kanban_boards", "task_counter")
