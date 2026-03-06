"""Add user submission fields to marketplace_bases

Revision ID: 0007_add_base_user_submissions
Revises: 0006_add_chat_position
Create Date: 2026-02-09

Adds created_by_user_id and visibility columns to marketplace_bases
to support user-submitted project templates.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_add_base_user_submissions"
down_revision: str | Sequence[str] | None = "0006_add_chat_position"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add created_by_user_id and visibility columns to marketplace_bases."""
    op.add_column(
        "marketplace_bases",
        sa.Column(
            "created_by_user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "marketplace_bases",
        sa.Column("visibility", sa.String(), nullable=True, server_default="public"),
    )


def downgrade() -> None:
    """Remove created_by_user_id and visibility columns from marketplace_bases."""
    op.drop_column("marketplace_bases", "visibility")
    op.drop_column("marketplace_bases", "created_by_user_id")
