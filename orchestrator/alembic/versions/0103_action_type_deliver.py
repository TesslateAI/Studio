"""Widen automation_actions.action_type CHECK to allow 'deliver'.

Revision ID: 0103_action_type_deliver
Revises: 0102_inbox_items
Create Date: 2026-05-07

Phase D of the workflow engine (issue #473). Adds the ``deliver``
step kind to the ``ck_automation_actions_action_type`` CHECK so the
new :class:`DeliverHandler` can run end-to-end. SQLite needs the
batch context because it cannot ``ALTER TABLE … DROP CONSTRAINT``;
Postgres handles it inside the same batch.

Mirrors migration 0083's pattern of widening the same constraint
when ``workflow.run`` was added.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0103_action_type_deliver"
down_revision = "0102_inbox_items"
branch_labels = None
depends_on = None


_CHECK_NAME = "ck_automation_actions_action_type"
_CHECK_OLD = "action_type IN ('agent.run', 'app.invoke', 'gateway.send', 'workflow.run')"
_CHECK_NEW = "action_type IN ('agent.run', 'app.invoke', 'gateway.send', 'workflow.run', 'deliver')"


def upgrade() -> None:
    with op.batch_alter_table("automation_actions") as batch:
        batch.drop_constraint(_CHECK_NAME, type_="check")
        batch.create_check_constraint(_CHECK_NAME, _CHECK_NEW)


def downgrade() -> None:
    with op.batch_alter_table("automation_actions") as batch:
        batch.drop_constraint(_CHECK_NAME, type_="check")
        batch.create_check_constraint(_CHECK_NAME, _CHECK_OLD)
