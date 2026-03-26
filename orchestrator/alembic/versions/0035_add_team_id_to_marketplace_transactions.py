"""Add team_id to marketplace_transactions

Revision ID: 0035_marketplace_team_id
Revises: 0034_rbac_teams
"""

revision = "0035_marketplace_team_id"
down_revision = "0034_rbac_teams"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    op.add_column(
        "marketplace_transactions",
        sa.Column("team_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_marketplace_transactions_team_id",
        "marketplace_transactions",
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
    op.drop_constraint(
        "fk_marketplace_transactions_team_id", "marketplace_transactions", type_="foreignkey"
    )
    op.drop_column("marketplace_transactions", "team_id")
