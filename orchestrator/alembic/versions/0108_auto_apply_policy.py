"""Add auto_apply_policy + diff_budget_consumed to automation_definitions (G3, #469).

Revision ID: 0108_auto_apply_policy
Revises: 0107_workflow_proposals
Create Date: 2026-05-11

G3 of the self-evolving workflow agent track. Two columns added:

* ``auto_apply_policy`` JSONB — when present, low-risk agent proposals
  whose diff paths are all in the policy's allowed_changes list bypass
  the approval queue and apply immediately after a successful dry-run.
  Null = always require approval (G2 behavior, the safe default).
* ``diff_budget_consumed`` INT — incremented on every auto-applied
  proposal; reset to 0 on every human-approved proposal. Feeds the
  G7 diff-budget guard. Default 0.

Policy shape::

    {
      "allowed_changes": ["step.config.timeout_seconds",
                          "step.config.prompt_text",
                          "step.retry_count"],
      "max_changes_per_proposal": 3,
      "require_test_run": true,
      "hard_blocked": ["compute_profile", "max_spend_per_run_usd",
                       "trigger.kind"]
    }
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0108_auto_apply_policy"
down_revision = "0107_workflow_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "automation_definitions",
        sa.Column("auto_apply_policy", sa.JSON(), nullable=True),
    )
    op.add_column(
        "automation_definitions",
        sa.Column(
            "diff_budget_consumed",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("automation_definitions", "diff_budget_consumed")
    op.drop_column("automation_definitions", "auto_apply_policy")
