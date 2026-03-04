"""Add is_byok flag to usage_logs table

Revision ID: 0016_usage_log_byok_flag
Revises: 0015_themes_marketplace
Create Date: 2026-02-22

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0016_usage_log_byok_flag"
down_revision = "0015_themes_marketplace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "usage_logs",
        sa.Column("is_byok", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("usage_logs", "is_byok")
