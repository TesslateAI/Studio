"""Add theme_preset column to users table

Revision ID: 0002_theme_preset
Revises: 0001_initial
Create Date: 2025-01-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_theme_preset"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add theme_preset column to users table."""
    op.add_column("users", sa.Column("theme_preset", sa.String(), nullable=True))


def downgrade() -> None:
    """Remove theme_preset column from users table."""
    op.drop_column("users", "theme_preset")
