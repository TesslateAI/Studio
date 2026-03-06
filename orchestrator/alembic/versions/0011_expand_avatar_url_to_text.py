"""Expand avatar_url column from VARCHAR(500) to TEXT

The frontend ImageUpload component generates base64 data URIs (~10-20KB)
for user profile pictures. VARCHAR(500) is too small, causing
StringDataRightTruncationError on profile save.

Revision ID: 0011_expand_avatar_url_to_text
Revises: 0010_default_visibility_private
Create Date: 2026-02-19

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0011_expand_avatar_url_to_text"
down_revision = "0010_default_visibility_private"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "avatar_url",
        existing_type=sa.String(500),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "avatar_url",
        existing_type=sa.Text(),
        type_=sa.String(500),
        existing_nullable=True,
    )
