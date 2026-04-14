"""AgentTask.message_id linking ticket to chat message.

Revision ID: 0052_agent_task_message_id
Revises: 0051_workspace_directories
Create Date: 2026-04-14 03:00:00.000000

Adds a nullable ``AgentTask.message_id`` FK so handoff bundles and the
unified workspace can query trajectory events (which are message-scoped
in ``agent_steps``) per ticket. Nullable + ondelete SET NULL: existing
tickets stay valid; deleting the parent message detaches without losing
the ticket history.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

revision: str = "0052_agent_task_message_id"
down_revision: str | None = "0051_workspace_directories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_tasks") as batch_op:
        batch_op.add_column(sa.Column("message_id", GUID(), nullable=True))
        batch_op.create_foreign_key(
            "fk_agent_tasks_message_id_messages",
            "messages",
            ["message_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_agent_tasks_message_id", ["message_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("agent_tasks") as batch_op:
        batch_op.drop_index("ix_agent_tasks_message_id")
        batch_op.drop_constraint("fk_agent_tasks_message_id_messages", type_="foreignkey")
        batch_op.drop_column("message_id")
