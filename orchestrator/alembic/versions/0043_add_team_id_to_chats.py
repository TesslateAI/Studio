"""Add team_id to chats for team-scoped chat sessions

Revision ID: 0043_chat_team_id
Revises: 0042_legacy_scopes
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043_chat_team_id"
down_revision: str | Sequence[str] | None = "0042_legacy_scopes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chats", sa.Column("team_id", sa.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_chats_team_id", "chats", "teams", ["team_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_chats_team_id", "chats", ["team_id"])

    # Backfill: set team_id from the user's default_team_id
    op.execute("""
        UPDATE chats SET team_id = u.default_team_id
        FROM users u WHERE chats.user_id = u.id AND chats.team_id IS NULL;
    """)


def downgrade() -> None:
    op.drop_index("ix_chats_team_id", table_name="chats")
    op.drop_constraint("fk_chats_team_id", "chats", type_="foreignkey")
    op.drop_column("chats", "team_id")
