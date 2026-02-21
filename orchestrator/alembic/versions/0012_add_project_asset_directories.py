"""Add project_asset_directories table for persisting user-created asset directories

Revision ID: 0012
Revises: 0011_expand_avatar_url_to_text
Create Date: 2026-02-21

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "0012_add_asset_directories"
down_revision = "0011_expand_avatar_url_to_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_asset_directories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "path", name="uq_project_asset_directory"),
    )
    op.create_index("ix_project_asset_directories_project_id", "project_asset_directories", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_project_asset_directories_project_id", table_name="project_asset_directories")
    op.drop_table("project_asset_directories")
