"""Add team_id to user_api_keys, user_custom_models, user_providers

Revision ID: 0044_keys_models_team
Revises: 0043_chat_team_id
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044_keys_models_team"
down_revision: str | Sequence[str] | None = "0043_chat_team_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ["user_api_keys", "user_custom_models", "user_providers"]


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("team_id", sa.UUID(as_uuid=True), nullable=True))
        op.create_foreign_key(f"fk_{table}_team_id", table, "teams", ["team_id"], ["id"], ondelete="SET NULL")
        op.create_index(f"ix_{table}_team_id", table, ["team_id"])

    # Backfill team_id from user's default_team_id
    for table in _TABLES:
        op.execute(f"""
            UPDATE {table} SET team_id = u.default_team_id
            FROM users u WHERE {table}.user_id = u.id AND {table}.team_id IS NULL;
        """)

    # Update user_providers unique constraint to include team_id
    op.drop_constraint("uq_user_provider_slug", "user_providers", type_="unique")
    op.create_unique_constraint(
        "uq_user_provider_slug_team", "user_providers", ["user_id", "slug", "team_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_user_provider_slug_team", "user_providers", type_="unique")
    op.create_unique_constraint("uq_user_provider_slug", "user_providers", ["user_id", "slug"])

    for table in reversed(_TABLES):
        op.drop_index(f"ix_{table}_team_id", table_name=table)
        op.drop_constraint(f"fk_{table}_team_id", table, type_="foreignkey")
        op.drop_column(table, "team_id")
