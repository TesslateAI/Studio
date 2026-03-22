"""Add exports column to containers and deployment_env to deployment_targets

Revision ID: 0032_exports_deploy_env
Revises: 0031_volume_hub
"""

revision = "0032_exports_deploy_env"
down_revision = "0031_volume_hub"
branch_labels = None
depends_on = None

import sqlalchemy as sa  # noqa: E402
from alembic import op  # noqa: E402


def upgrade() -> None:
    op.add_column("containers", sa.Column("exports", sa.JSON(), nullable=True))
    op.add_column("deployment_targets", sa.Column("deployment_env", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("deployment_targets", "deployment_env")
    op.drop_column("containers", "exports")
