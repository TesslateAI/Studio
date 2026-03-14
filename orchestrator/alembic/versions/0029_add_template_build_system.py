"""Add template build system: template_builds table, template_slug, and template_storage_class

Creates the template_builds table to track btrfs template build lifecycle
for marketplace bases, adds template_slug to marketplace_bases to
indicate when a pre-built template is available for instant project creation,
and adds template_storage_class to projects for template-based PVC creation.

Revision ID: 0029_template_builds
Revises: 0028_fix_fk_ondelete
Create Date: 2026-03-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision = "0029_template_builds"
down_revision = "0028_fix_fk_ondelete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create template_builds table
    op.create_table(
        "template_builds",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "base_id",
            UUID(as_uuid=True),
            sa.ForeignKey("marketplace_bases.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("base_slug", sa.String(), nullable=False, index=True),
        sa.Column("git_commit_sha", sa.String(40), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("build_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("template_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # 2. Add template_slug to marketplace_bases
    op.add_column(
        "marketplace_bases",
        sa.Column("template_slug", sa.String(100), nullable=True),
    )

    # 3. Add template_storage_class to projects
    op.add_column(
        "projects",
        sa.Column("template_storage_class", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "template_storage_class")
    op.drop_column("marketplace_bases", "template_slug")
    op.drop_table("template_builds")
