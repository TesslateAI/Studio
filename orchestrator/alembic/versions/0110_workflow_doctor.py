"""G5 (#469): workflow_event trigger kind + per-workflow doctor flags.

Revision ID: 0110_workflow_doctor
Revises: 0109_workflow_health
Create Date: 2026-05-11

Schema additions:

* automation_triggers.kind CHECK widens to accept ``workflow_event``
  so an automation can subscribe to events from another automation
  (the doctor watches its target's run.failed / step.failed events).
* automation_definitions adds doctor_enabled BOOLEAN (default false)
  and doctor_automation_id GUID (FK to the per-workflow doctor).
"""

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision = "0110_workflow_doctor"
down_revision = "0109_workflow_health"
branch_labels = None
depends_on = None


_TRIG_NAME = "ck_automation_triggers_kind"
_TRIG_OLD = (
    "kind IN ('cron', 'webhook', 'app_invocation', 'manual', 'slack_message', 'email_inbound')"
)
_TRIG_NEW = (
    "kind IN ('cron', 'webhook', 'app_invocation', 'manual', "
    "'slack_message', 'email_inbound', 'workflow_event')"
)


def upgrade() -> None:
    with op.batch_alter_table("automation_triggers") as batch:
        batch.drop_constraint(_TRIG_NAME, type_="check")
        batch.create_check_constraint(_TRIG_NAME, _TRIG_NEW)

    # Self-referential FK column needs batch mode on SQLite — bare
    # op.add_column with a ForeignKey calls add_constraint internally
    # and SQLite has no ALTER TABLE ADD CONSTRAINT support. The Boolean
    # column has no constraint but is bundled in the same batch so the
    # two additions stay atomic on the test schema.
    with op.batch_alter_table("automation_definitions") as batch:
        batch.add_column(
            sa.Column(
                "doctor_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column(
                "doctor_automation_id",
                GUID(),
                sa.ForeignKey(
                    "automation_definitions.id",
                    name="fk_automation_definitions_doctor_automation_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("automation_definitions") as batch:
        batch.drop_column("doctor_automation_id")
        batch.drop_column("doctor_enabled")
    with op.batch_alter_table("automation_triggers") as batch:
        batch.drop_constraint(_TRIG_NAME, type_="check")
        batch.create_check_constraint(_TRIG_NAME, _TRIG_OLD)
