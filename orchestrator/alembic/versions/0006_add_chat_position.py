"""Add chat_position column to users table

Revision ID: 0006_add_chat_position
Revises: 0005_billing_credits_system
Create Date: 2026-01-27

This migration adds the chat_position preference for users to choose
where the chat panel appears in the builder (left, center, or right).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_add_chat_position"
down_revision: str | Sequence[str] | None = "0005_billing_credits_system"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add chat_position column to users table."""
    op.add_column(
        "users", sa.Column("chat_position", sa.String(10), nullable=True, server_default="center")
    )


def downgrade() -> None:
    """Remove chat_position column from users table."""
    op.drop_column("users", "chat_position")
