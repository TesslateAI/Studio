"""Widen automation_triggers.kind CHECK for Phase E inbound triggers.

Revision ID: 0104_trigger_kinds_phase_e
Revises: 0103_action_type_deliver
Create Date: 2026-05-08

Phase E of the workflow engine (issue #474). Adds ``slack_message`` and
``email_inbound`` to the trigger-kind CHECK so the new trigger
adapters in ``services/triggers/`` can persist subscription rows.
The ``kind`` column is and stays a String + CHECK (not a Postgres
ENUM) so future kinds extend without an ALTER ENUM round under
SQLite parity.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0104_trigger_kinds_phase_e"
down_revision = "0103_action_type_deliver"
branch_labels = None
depends_on = None


_NAME = "ck_automation_triggers_kind"
_OLD = "kind IN ('cron', 'webhook', 'app_invocation', 'manual')"
_NEW = "kind IN ('cron', 'webhook', 'app_invocation', 'manual', 'slack_message', 'email_inbound')"


def upgrade() -> None:
    with op.batch_alter_table("automation_triggers") as batch:
        batch.drop_constraint(_NAME, type_="check")
        batch.create_check_constraint(_NAME, _NEW)


def downgrade() -> None:
    with op.batch_alter_table("automation_triggers") as batch:
        batch.drop_constraint(_NAME, type_="check")
        batch.create_check_constraint(_NAME, _OLD)
