"""Add workflow_health_snapshots (G4, issue #469).

Revision ID: 0109_workflow_health
Revises: 0108_auto_apply_policy
Create Date: 2026-05-11

G4 of the self-evolving workflow agent track. A periodic rollup of
per-workflow health metrics so the doctor agent (G5) reads "is this
workflow healthy?" in O(1) instead of scanning event logs.

Schema notes:

* (automation_id, window) is UNIQUE so the aggregator can upsert.
* window is 'short' (e.g. last 24h) or 'long' (last 7d). Two
  rolling windows lets the doctor distinguish a flash failure
  from a sustained problem.
* Numeric counters are nullable when the window has no runs yet.
"""

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision = "0109_workflow_health"
down_revision = "0108_auto_apply_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_health_snapshots",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "automation_id",
            GUID(),
            sa.ForeignKey("automation_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("window", sa.String(16), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("awaiting_approval_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_rate", sa.Numeric(4, 3), nullable=True),
        sa.Column("median_duration_ms", sa.Integer(), nullable=True),
        sa.Column("p95_duration_ms", sa.Integer(), nullable=True),
        sa.Column("spend_p50_usd", sa.Numeric(12, 4), nullable=True),
        sa.Column("spend_p95_usd", sa.Numeric(12, 4), nullable=True),
        sa.Column("most_common_error_kind", sa.Text(), nullable=True),
        sa.Column("most_common_failed_step_ordinal", sa.Integer(), nullable=True),
        sa.Column(
            "last_failed_run_id",
            GUID(),
            sa.ForeignKey("automation_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("last_failed_step_ordinal", sa.Integer(), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("runs_since_last_change", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("open_proposal_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generation_at_window_start", sa.Integer(), nullable=True),
        sa.Column("generation_at_window_end", sa.Integer(), nullable=True),
        sa.UniqueConstraint("automation_id", "window", name="uq_workflow_health_automation_window"),
        sa.CheckConstraint(
            "\"window\" IN ('short', 'long')",
            name="ck_workflow_health_window",
        ),
    )


def downgrade() -> None:
    op.drop_table("workflow_health_snapshots")
