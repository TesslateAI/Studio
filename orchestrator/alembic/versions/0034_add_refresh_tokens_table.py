"""Add refresh_tokens table for DB-backed session persistence

Revision ID: 0034_refresh_tokens
Revises: 0033_container_build
Create Date: 2026-03-26 13:24:16.277085

"""

from collections.abc import Sequence

import sqlalchemy as sa
from app.types.guid import GUID
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0034_refresh_tokens"
down_revision: str | Sequence[str] | None = "0033_container_build"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create refresh_tokens table for long-lived session persistence."""
    op.create_table(
        "refresh_tokens",
        sa.Column("token", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="cascade"),
            nullable=False,
            index=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
    )
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])


def downgrade() -> None:
    """Drop refresh_tokens table."""
    op.drop_index("ix_refresh_tokens_expires_at", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
