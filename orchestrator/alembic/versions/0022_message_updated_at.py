"""Add updated_at column to messages table

Revision ID: 0022_message_updated_at
Revises: 0021_agent_steps_sessions
Create Date: 2026-02-26

Messages are updated after agent runs (content and metadata finalized),
so updated_at tracks when the last modification occurred.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0022_message_updated_at"
down_revision = "0021_agent_steps_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "updated_at")
