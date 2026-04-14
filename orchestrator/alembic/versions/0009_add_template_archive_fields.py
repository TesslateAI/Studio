"""Add template archive fields to marketplace_bases

Revision ID: 0009
Revises: 0008
Create Date: 2026-02-10

"""

import sqlalchemy as sa
from alembic import op
from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision = "0009_add_template_archive_fields"
down_revision = "0008_add_two_factor_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add source_type column (git or archive)
    op.add_column(
        "marketplace_bases",
        sa.Column("source_type", sa.String(length=20), server_default="git", nullable=False),
    )

    # Add archive storage columns
    op.add_column(
        "marketplace_bases",
        sa.Column("archive_path", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "marketplace_bases",
        sa.Column("archive_size_bytes", sa.BigInteger(), nullable=True),
    )

    # Add source project reference
    op.add_column(
        "marketplace_bases",
        sa.Column("source_project_id", GUID(), nullable=True),
    )
    with op.batch_alter_table("marketplace_bases") as batch_op:
        batch_op.create_foreign_key(
            "fk_marketplace_bases_source_project",
            "projects",
            ["source_project_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # Make git_repo_url nullable (archive templates don't use git)
    with op.batch_alter_table("marketplace_bases") as batch_op:
        batch_op.alter_column("git_repo_url", existing_type=sa.String(500), nullable=True)


def downgrade() -> None:
    # Restore git_repo_url to NOT NULL (set NULLs to empty string first)
    op.execute("UPDATE marketplace_bases SET git_repo_url = '' WHERE git_repo_url IS NULL")
    with op.batch_alter_table("marketplace_bases") as batch_op:
        batch_op.alter_column("git_repo_url", existing_type=sa.String(500), nullable=False)

    with op.batch_alter_table("marketplace_bases") as batch_op:
        batch_op.drop_constraint("fk_marketplace_bases_source_project", type_="foreignkey")
    op.drop_column("marketplace_bases", "source_project_id")
    op.drop_column("marketplace_bases", "archive_size_bytes")
    op.drop_column("marketplace_bases", "archive_path")
    op.drop_column("marketplace_bases", "source_type")
