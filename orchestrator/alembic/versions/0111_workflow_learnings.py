"""G6 (#469): workflow_learnings cross-workflow memory.

Revision ID: 0111_workflow_learnings
Revises: 0110_workflow_doctor
Create Date: 2026-05-11

The doctor records "what worked" when a proposal it auto-applied
goes on to succeed N times. Future doctor runs against any workflow
in the same team can read these learnings as prior knowledge.

Schema:
* tag is the cluster key (e.g. "deliver.slack.timeout") — agent
  picks a short tag at record time.
* symptom_pattern + proposed_fix are JSON for flexible matching.
* (team_id, tag, created_by_run_id) is UNIQUE so the same run can't
  record the same learning twice.
"""

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision = "0111_workflow_learnings"
down_revision = "0110_workflow_doctor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_learnings",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "team_id",
            GUID(),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tag", sa.String(64), nullable=False),
        sa.Column("symptom_pattern", sa.JSON(), nullable=True),
        sa.Column("proposed_fix", sa.JSON(), nullable=True),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "last_applied_run_id",
            GUID(),
            sa.ForeignKey("automation_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_run_id",
            GUID(),
            sa.ForeignKey("automation_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
    )
    op.create_index(
        "ix_workflow_learnings_team_tag",
        "workflow_learnings",
        ["team_id", "tag"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_learnings_team_tag", table_name="workflow_learnings")
    op.drop_table("workflow_learnings")
