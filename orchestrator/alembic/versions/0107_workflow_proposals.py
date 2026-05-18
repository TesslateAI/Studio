"""Add workflow_proposals table (G2, issue #469).

Revision ID: 0107_workflow_proposals
Revises: 0106_workflow_versions
Create Date: 2026-05-11

G2 of the self-evolving workflow agent track. An agent (or human)
authoring a change to an automation writes a ``WorkflowProposal`` row
instead of mutating the live definition directly. The proposal is
resolved by one of two paths:

* approval-required → routes through the existing
  ``AutomationApprovalRequest`` + ``delivery_fallback`` so the user
  gets the same Slack / email / web approval card they already see for
  risky tool calls. On approve, the proposal is applied (new
  WorkflowVersion + head pointer flip + child rows replaced).
* auto-apply (G3) → bypasses approval after a successful dry-run
  against an ``auto_apply_policy`` whitelist.

G2 ships the table + the manual-approval path. G3 wires auto-apply.

Schema notes:

* ``from_version_id`` records the WorkflowVersion the proposal was
  drafted against. The agent's diff is relative to that snapshot.
* ``to_payload`` is the FULL proposed shape (same schema as
  WorkflowVersion.payload). Diff is computed at decide-time.
* ``diff_summary`` is a structured list of {path, op, before, after}
  records so the UI / approval card can render a compact diff without
  re-deriving it.
* ``status`` enum: submitted | approved | rejected | applied |
  reverted | expired | withdrawn.
* ``applied_version_id`` is set when status -> applied; it's the new
  WorkflowVersion the proposal produced.
* ``approval_request_id`` ties to the existing approval queue when
  the proposal needs human review.
* ``expires_at`` lets a background sweep mark stale proposals as
  expired so the queue doesn't grow unbounded.
"""

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision = "0107_workflow_proposals"
down_revision = "0106_workflow_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_proposals",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "automation_id",
            GUID(),
            sa.ForeignKey("automation_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "from_version_id",
            GUID(),
            sa.ForeignKey("workflow_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("to_payload", sa.JSON(), nullable=False),
        sa.Column("diff_summary", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "risk_class",
            sa.String(16),
            nullable=False,
            server_default="medium",
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="submitted",
        ),
        sa.Column(
            "approval_request_id",
            GUID(),
            sa.ForeignKey("automation_approval_requests.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "applied_version_id",
            GUID(),
            sa.ForeignKey("workflow_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "proposer_run_id",
            GUID(),
            sa.ForeignKey("automation_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "proposer_user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewer_user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewer_comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('submitted', 'approved', 'rejected', 'applied', "
            "'reverted', 'expired', 'withdrawn')",
            name="ck_workflow_proposals_status",
        ),
        sa.CheckConstraint(
            "risk_class IN ('low', 'medium', 'high')",
            name="ck_workflow_proposals_risk_class",
        ),
    )
    op.create_index(
        "ix_workflow_proposals_automation_status",
        "workflow_proposals",
        ["automation_id", "status"],
    )
    op.create_index(
        "ix_workflow_proposals_expires",
        "workflow_proposals",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_proposals_expires", table_name="workflow_proposals")
    op.drop_index(
        "ix_workflow_proposals_automation_status",
        table_name="workflow_proposals",
    )
    op.drop_table("workflow_proposals")
