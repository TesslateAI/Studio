"""Add base_url to user_api_keys, available_models to user_providers

Revision ID: 0013
Revises: 0012_add_asset_directories
Create Date: 2026-02-21

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0013_add_key_base_url"
down_revision = "0012_add_asset_directories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_api_keys", sa.Column("base_url", sa.String(), nullable=True))
    op.add_column("user_providers", sa.Column("available_models", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_providers", "available_models")
    op.drop_column("user_api_keys", "base_url")
