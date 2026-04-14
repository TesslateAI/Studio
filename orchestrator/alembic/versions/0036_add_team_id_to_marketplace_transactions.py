"""Add team_id to marketplace_transactions

Revision ID: 0036_marketplace_team_id
Revises: 0035_rbac_teams
"""

revision = "0036_marketplace_team_id"
down_revision = "0035_rbac_teams"
branch_labels = None
depends_on = None

import sqlalchemy as sa  # noqa: E402
from app.types.guid import GUID
from alembic import op  # noqa: E402


def upgrade() -> None:
    op.add_column(
        "marketplace_transactions",
        sa.Column("team_id", GUID(), nullable=True),
    )
    with op.batch_alter_table("marketplace_transactions") as batch_op:
        batch_op.create_foreign_key(
            "fk_marketplace_transactions_team_id",
            "teams",
            ["team_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_marketplace_transactions_team_id",
        "marketplace_transactions",
        ["team_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_marketplace_transactions_team_id", table_name="marketplace_transactions")
    with op.batch_alter_table("marketplace_transactions") as batch_op:
        batch_op.drop_constraint("fk_marketplace_transactions_team_id", type_="foreignkey")
    op.drop_column("marketplace_transactions", "team_id")
