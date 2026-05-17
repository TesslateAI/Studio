"""G7 (#469): convergence guards on automation_definitions.

Revision ID: 0112_convergence_guards
Revises: 0111_workflow_learnings
Create Date: 2026-05-11

Three guards keep agent-authored proposals from thrashing:

* min_seconds_between_self_edits INT (default 86400 = 24h): cooldown
  applied to back-to-back agent proposals on the same workflow.
* diff_budget_max INT (default 5): cap on auto-applied edits before
  routing to manual approval; resets on human approve.
* last_self_edit_at TIMESTAMP: updated whenever the doctor (or any
  agent) auto-applies a proposal, so the cooldown check has a
  timestamp.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0112_convergence_guards"
down_revision = "0111_workflow_learnings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "automation_definitions",
        sa.Column(
            "min_seconds_between_self_edits",
            sa.Integer(),
            nullable=False,
            server_default="86400",
        ),
    )
    op.add_column(
        "automation_definitions",
        sa.Column(
            "diff_budget_max",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
    )
    op.add_column(
        "automation_definitions",
        sa.Column(
            "last_self_edit_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("automation_definitions", "last_self_edit_at")
    op.drop_column("automation_definitions", "diff_budget_max")
    op.drop_column("automation_definitions", "min_seconds_between_self_edits")
