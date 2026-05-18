"""Add automation_step_runs table for the workflow step graph engine.

Revision ID: 0099_automation_step_runs
Revises: 0098_container_resources
Create Date: 2026-05-07

Phase A of the workflow engine (issue #470). Adds a per-step execution
record so multi-step automations can track each step's status, input,
output, cost, and artifacts independently from the parent ``AutomationRun``.

Existing single-step automations are unaffected: the dispatcher falls
back to the legacy single-action path when the step graph has zero or
one row. Multi-step rows use the engine in
``app/services/workflows/engine.py`` which reads the actions in ordinal
order and inserts one ``automation_step_runs`` row per step.

Status enum mirrors ``AutomationRun.status`` with the addition of
``skipped`` for branches that the DAG executor will surface in Phase F.
"""

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision = "0099_automation_step_runs"
down_revision = "0098_container_resources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "automation_step_runs",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "automation_run_id",
            GUID(),
            sa.ForeignKey("automation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "automation_action_id",
            GUID(),
            sa.ForeignKey("automation_actions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input", sa.JSON(), nullable=True),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("spend_usd", sa.Numeric(12, 4), nullable=True),
        sa.Column("artifact_ids", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', "
            "'awaiting_approval', 'skipped', 'cancelled')",
            name="ck_automation_step_runs_status",
        ),
    )
    op.create_index(
        "ix_automation_step_runs_run_ordinal",
        "automation_step_runs",
        ["automation_run_id", "ordinal"],
    )
    op.create_index(
        "ix_automation_step_runs_status",
        "automation_step_runs",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_automation_step_runs_status",
        table_name="automation_step_runs",
    )
    op.drop_index(
        "ix_automation_step_runs_run_ordinal",
        table_name="automation_step_runs",
    )
    op.drop_table("automation_step_runs")
