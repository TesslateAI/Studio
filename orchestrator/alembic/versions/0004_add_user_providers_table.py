"""Add user_providers table for custom BYOK providers

Revision ID: 0004_add_user_providers_table
Revises: 0003_add_themes_table
Create Date: 2025-01-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004_add_user_providers_table"
down_revision: str | None = "0003_add_themes_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create user_providers table for custom BYOK providers
    op.create_table(
        "user_providers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, index=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("api_type", sa.String(), server_default="openai"),
        sa.Column("default_headers", postgresql.JSON(), server_default="{}"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    # Add unique constraint for user_id + slug combination
    op.create_unique_constraint("uq_user_provider_slug", "user_providers", ["user_id", "slug"])

    # Add index for user_id for faster lookups
    op.create_index("ix_user_providers_user_id", "user_providers", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_providers_user_id", table_name="user_providers")
    op.drop_constraint("uq_user_provider_slug", "user_providers", type_="unique")
    op.drop_table("user_providers")
