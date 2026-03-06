"""Add disabled_models JSON column to users table

Revision ID: 0017_disabled_models
Revises: 0016_usage_log_byok_flag
Create Date: 2026-02-22

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0017_disabled_models"
down_revision = "0016_usage_log_byok_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("disabled_models", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "disabled_models")
