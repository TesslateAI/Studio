"""Expression index on automation_triggers.config->>'watched_automation_id'.

Revision ID: 0113_workflow_event_index
Revises: 0112_convergence_guards
Create Date: 2026-05-17

route_workflow_event (services/triggers/workflow_event.py) used to
SELECT every workflow_event trigger row, then filter in Python on the
config JSON's watched_automation_id. With N workflows that all have
doctor enabled, every error.raised emit scanned the full table.

This index lets the new WHERE clause (``config->>'watched_automation_id'
= :id``) probe directly. Partial on kind+is_active so it stays tiny —
only the rows the route can match are in the tree.

Postgres-only path uses a btree on the JSON cast; we skip on SQLite
where the test fixture uses Base.metadata.create_all and the cost of
the missing index is irrelevant.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0113_workflow_event_index"
down_revision = "0112_convergence_guards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_automation_triggers_watched_workflow
        ON automation_triggers ((config->>'watched_automation_id'))
        WHERE kind = 'workflow_event' AND is_active = true
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_automation_triggers_watched_workflow")
