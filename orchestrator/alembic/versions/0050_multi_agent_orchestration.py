"""Multi-agent orchestration: agent_tasks, agent_budgets, projects.mission

Revision ID: 0050_multi_agent_orchestration
Revises: 0049_project_runtime_fields
Create Date: 2026-04-14 01:00:00.000000

Adds the MVP skeleton for the multi-agent orchestration system:

- ``agent_tasks`` — work tickets ("TSK-0001") allocated per project, with
  parent/child relations, status lifecycle, and per-ticket
  ``requires_approval_for`` gating.
- ``agent_budgets`` — monthly USD caps per (agent, project). A row with
  ``project_id IS NULL`` acts as the agent-wide fallback.
- ``projects.mission`` — optional long-form mission statement propagated
  into agent context as goal ancestry.

SQLite-safe: batch_alter_table for the projects column; plain create_table
for the new tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision: str = "0050_multi_agent_orchestration"
down_revision: str | Sequence[str] | None = "0049_project_runtime_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_tasks",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("ref_id", sa.String(length=16), nullable=False),
        sa.Column(
            "project_id",
            GUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_task_id",
            GUID(),
            sa.ForeignKey("agent_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("goal_ancestry", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("requires_approval_for", sa.JSON(), nullable=True),
        sa.Column("assignee_agent_id", GUID(), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("ref_id", name="uq_agent_tasks_ref_id"),
    )
    op.create_index("ix_agent_tasks_ref_id", "agent_tasks", ["ref_id"], unique=True)
    op.create_index("ix_agent_tasks_project_id", "agent_tasks", ["project_id"])
    op.create_index("ix_agent_tasks_status", "agent_tasks", ["status"])

    op.create_table(
        "agent_budgets",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("agent_id", GUID(), nullable=False),
        sa.Column("project_id", GUID(), nullable=True),
        sa.Column("monthly_limit_usd", sa.Numeric(10, 4), nullable=False),
        sa.Column(
            "spent_usd",
            sa.Numeric(10, 4),
            nullable=False,
            server_default="0",
        ),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "agent_id", "project_id", name="uq_agent_budgets_agent_project"
        ),
    )
    op.create_index("ix_agent_budgets_agent_id", "agent_budgets", ["agent_id"])

    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(sa.Column("mission", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("mission")

    op.drop_index("ix_agent_budgets_agent_id", table_name="agent_budgets")
    op.drop_table("agent_budgets")

    op.drop_index("ix_agent_tasks_status", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_project_id", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_ref_id", table_name="agent_tasks")
    op.drop_table("agent_tasks")
