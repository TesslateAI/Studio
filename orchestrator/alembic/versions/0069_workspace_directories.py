"""Workspace directories + agent_task_directories join table.

Revision ID: 0054_workspace_directories
Revises: 0053_multi_agent_orchestration
Create Date: 2026-04-14 02:00:00.000000

Adds the unified workspace directory model used by the desktop agents
workspace view:

- ``directories`` — user-scoped workspace entries referencing an
  on-disk path with optional runtime / project / git-root metadata.
- ``agent_task_directories`` — many-to-many linking agent tickets to
  directories so a session can report the on-disk roots it operated on.

SQLite-safe: plain ``create_table`` calls with explicit FK ondelete
semantics. Unique (user_id, path) guards against duplicate rows for the
same canonical path.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision: str = "0069_workspace_directories"
down_revision: str | Sequence[str] | None = "0068_multi_agent_orchestration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "directories",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("runtime", sa.String(length=16), nullable=True),
        sa.Column(
            "project_id",
            GUID(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("git_root", sa.String(length=1024), nullable=True),
        sa.Column("last_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", "path", name="uq_directories_user_path"),
    )
    op.create_index("ix_directories_user_id", "directories", ["user_id"])
    op.create_index("ix_directories_project_id", "directories", ["project_id"])

    op.create_table(
        "agent_task_directories",
        sa.Column(
            "ticket_id",
            GUID(),
            sa.ForeignKey("agent_tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "directory_id",
            GUID(),
            sa.ForeignKey("directories.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index(
        "ix_agent_task_directories_directory_id",
        "agent_task_directories",
        ["directory_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_task_directories_directory_id", table_name="agent_task_directories")
    op.drop_table("agent_task_directories")
    op.drop_index("ix_directories_project_id", table_name="directories")
    op.drop_index("ix_directories_user_id", table_name="directories")
    op.drop_table("directories")
