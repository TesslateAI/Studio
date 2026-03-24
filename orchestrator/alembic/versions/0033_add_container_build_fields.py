"""Add build_command, output_directory, and framework to containers

Revision ID: 0033_container_build
Revises: 0032_exports_deploy_env
"""

revision = "0033_container_build"
down_revision = "0032_exports_deploy_env"
branch_labels = None
depends_on = None

import sqlalchemy as sa  # noqa: E402
from alembic import op  # noqa: E402


def upgrade() -> None:
    op.add_column("containers", sa.Column("build_command", sa.String(), nullable=True))
    op.add_column("containers", sa.Column("output_directory", sa.String(), nullable=True))
    op.add_column("containers", sa.Column("framework", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("containers", "framework")
    op.drop_column("containers", "output_directory")
    op.drop_column("containers", "build_command")
