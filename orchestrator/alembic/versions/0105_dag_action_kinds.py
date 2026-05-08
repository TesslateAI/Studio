"""Widen automation_actions.action_type CHECK for Phase F DAG step kinds.

Revision ID: 0105_dag_action_kinds
Revises: 0104_trigger_kinds_phase_e
Create Date: 2026-05-08

Phase F of the workflow engine (issue #475). Adds three DAG-orchestration
step kinds to the action_type CHECK: ``sub_workflow``, ``branch``, and
``parallel``. ``parallel`` is reserved for a Phase F follow-up; the
CHECK is widened now so the schema is forward-compatible without
another migration round.

Mirrors the batch pattern from migrations 0083 and 0103.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0105_dag_action_kinds"
down_revision = "0104_trigger_kinds_phase_e"
branch_labels = None
depends_on = None


_NAME = "ck_automation_actions_action_type"
_OLD = "action_type IN ('agent.run', 'app.invoke', 'gateway.send', 'workflow.run', 'deliver')"
_NEW = (
    "action_type IN ('agent.run', 'app.invoke', 'gateway.send', "
    "'workflow.run', 'deliver', 'sub_workflow', 'branch', 'parallel')"
)


def upgrade() -> None:
    with op.batch_alter_table("automation_actions") as batch:
        batch.drop_constraint(_NAME, type_="check")
        batch.create_check_constraint(_NAME, _NEW)


def downgrade() -> None:
    with op.batch_alter_table("automation_actions") as batch:
        batch.drop_constraint(_NAME, type_="check")
        batch.create_check_constraint(_NAME, _OLD)
