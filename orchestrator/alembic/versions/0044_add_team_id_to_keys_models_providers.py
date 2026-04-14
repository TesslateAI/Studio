"""Add team_id to user_api_keys, user_custom_models, user_providers

Revision ID: 0044_keys_models_team
Revises: 0043_chat_team_id
"""

from collections.abc import Sequence

import sqlalchemy as sa
from app.types.guid import GUID
from alembic import op

revision: str = "0044_keys_models_team"
down_revision: str | Sequence[str] | None = "0043_chat_team_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ["user_api_keys", "user_custom_models", "user_providers"]


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("team_id", GUID(), nullable=True))
        with op.batch_alter_table(table) as batch_op:
            batch_op.create_foreign_key(f"fk_{table}_team_id", "teams", ["team_id"], ["id"], ondelete="SET NULL")
        op.create_index(f"ix_{table}_team_id", table, ["team_id"])

    is_postgres = op.get_bind().dialect.name == "postgresql"

    # Backfill team_id from user's default_team_id
    if is_postgres:
        for table in _TABLES:
            op.execute(f"""
                UPDATE {table} SET team_id = u.default_team_id
                FROM users u WHERE {table}.user_id = u.id AND {table}.team_id IS NULL;
            """)

    # Update user_providers unique constraint to include team_id
    with op.batch_alter_table("user_providers") as batch_op:
        batch_op.drop_constraint("uq_user_provider_slug", type_="unique")
        batch_op.create_unique_constraint(
            "uq_user_provider_slug_team", ["user_id", "slug", "team_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("user_providers") as batch_op:
        batch_op.drop_constraint("uq_user_provider_slug_team", type_="unique")
        batch_op.create_unique_constraint("uq_user_provider_slug", ["user_id", "slug"])

    for table in reversed(_TABLES):
        op.drop_index(f"ix_{table}_team_id", table_name=table)
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(f"fk_{table}_team_id", type_="foreignkey")
        op.drop_column(table, "team_id")
